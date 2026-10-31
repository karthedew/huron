import {
	createCipheriv,
	createDecipheriv,
	createHash,
	randomBytes,
	timingSafeEqual
} from 'node:crypto';
import type { Cookies } from '@sveltejs/kit';
import type { ExchangeOut } from '$api/openapi';
import type { JsonValue } from '$api/types';
import { getConfig, publicOrigin, type Config, type OidcSettings } from './config';
import { CookieJar, TRANSACTION_MAX_AGE_SECONDS, transactionCookieBase } from './cookies';
import { HuronApiError, exchange } from './huron-api';
import { isJsonObject, parseJson } from './json';
import { loginPath, safeReturnTo } from './return-to';
import { SessionError, sessionStore, type SessionStore } from './sessions';

export const SIGN_IN_ERROR_CODES = [
	'state_mismatch',
	'idp_error',
	'idp_unavailable',
	'token_rejected',
	'groups_unavailable',
	'service_unavailable',
	'config'
] as const;
export type SignInErrorCode = (typeof SIGN_IN_ERROR_CODES)[number];

/** A failed sign-in step. `reason` is for the log; it never holds tokens, codes or secrets. */
export class SignInError extends Error {
	readonly code: SignInErrorCode;

	constructor(code: SignInErrorCode, reason: string) {
		super(`${code}: ${reason}`);
		this.name = 'SignInError';
		this.code = code;
	}
}

/** At most this many sign-ins may be in flight per browser; the oldest gives way. */
export const MAX_TRANSACTIONS = 3;
export const DISCOVERY_TTL_MS = 60 * 60 * 1000;
export const DISCOVERY_FAILURE_TTL_MS = 5 * 1000;

/** A sign-in in progress, sealed into its cookie. */
export interface Transaction {
	state: string;
	nonce: string;
	codeVerifier: string;
	returnTo: string;
	/** Epoch seconds. */
	exp: number;
}

export interface OpenedTransaction {
	transaction: Transaction;
	expired: boolean;
}

const SEAL_CONTEXT = Buffer.from('huron-web oidc transaction v1');
const IV_BYTES = 12;
const TAG_BYTES = 16;

/** Seals transactions with AES-256-GCM, so the browser can carry them but not read or forge them. */
export class TransactionSealer {
	readonly #key: Buffer;

	constructor(key: Uint8Array) {
		if (key.length !== 32) throw new RangeError('the transaction key must be 32 bytes');
		this.#key = Buffer.from(key);
	}

	seal(transaction: Transaction): string {
		const iv = randomBytes(IV_BYTES);
		const cipher = createCipheriv('aes-256-gcm', this.#key, iv, { authTagLength: TAG_BYTES });
		cipher.setAAD(SEAL_CONTEXT);
		const body = Buffer.concat([
			cipher.update(JSON.stringify(transaction), 'utf8'),
			cipher.final()
		]);
		return Buffer.concat([iv, body, cipher.getAuthTag()]).toString('base64url');
	}

	/** The transaction, or `null` when the value was not sealed by this key. */
	open(sealed: string, nowSeconds: number): OpenedTransaction | null {
		if (!/^[A-Za-z0-9_-]+$/.test(sealed)) return null;
		const data = Buffer.from(sealed, 'base64url');
		if (data.length <= IV_BYTES + TAG_BYTES) return null;
		let text: string;
		try {
			const decipher = createDecipheriv('aes-256-gcm', this.#key, data.subarray(0, IV_BYTES), {
				authTagLength: TAG_BYTES
			});
			decipher.setAAD(SEAL_CONTEXT);
			decipher.setAuthTag(data.subarray(data.length - TAG_BYTES));
			text = Buffer.concat([
				decipher.update(data.subarray(IV_BYTES, data.length - TAG_BYTES)),
				decipher.final()
			]).toString('utf8');
		} catch {
			return null;
		}
		const transaction = transactionFrom(parseJson(text));
		return transaction === null ? null : { transaction, expired: transaction.exp <= nowSeconds };
	}
}

declare global {
	// One key per process, kept across Vite module reloads so sign-ins in flight survive them.
	var huronWebTransactionKey: Uint8Array | undefined;
}

/** The sealer of this process, with a random key made at first use. */
export function transactionSealer(): TransactionSealer {
	globalThis.huronWebTransactionKey ??= randomBytes(32);
	return new TransactionSealer(globalThis.huronWebTransactionKey);
}

/** 32 random bytes, base64url (43 characters): states, nonces and PKCE verifiers. */
export function randomToken(): string {
	return randomBytes(32).toString('base64url');
}

/** The PKCE S256 challenge of a verifier. */
export function codeChallenge(verifier: string): string {
	return createHash('sha256').update(verifier, 'ascii').digest('base64url');
}

/** Constant-time equality of two strings. */
export function safeEqual(a: string, b: string): boolean {
	const left = Buffer.from(a, 'utf8');
	const right = Buffer.from(b, 'utf8');
	return left.length === right.length && timingSafeEqual(left, right);
}

export interface Discovery {
	issuer: string;
	authorizationEndpoint: string;
	tokenEndpoint: string;
	endSessionEndpoint: string | null;
}

export interface OidcClientOptions {
	settings: OidcSettings;
	timeoutMs: number;
	fetch?: typeof fetch;
	now?: () => number;
}

type DiscoveryOutcome = { ok: true; discovery: Discovery } | { ok: false; failure: SignInError };

/** The company IdP: discovery (cached), authorization URLs, code redemption, ID token checks. */
export class OidcClient {
	readonly #settings: OidcSettings;
	readonly #timeoutMs: number;
	readonly #fetch: typeof fetch;
	readonly #now: () => number;
	#cache: { until: number; outcome: DiscoveryOutcome } | undefined;
	#inflight: Promise<DiscoveryOutcome> | undefined;

	constructor({
		settings,
		timeoutMs,
		fetch = globalThis.fetch,
		now = Date.now
	}: OidcClientOptions) {
		this.#settings = settings;
		this.#timeoutMs = timeoutMs;
		this.#fetch = fetch;
		this.#now = now;
	}

	/** The provider metadata; answers are cached for an hour, failures for five seconds. */
	async discover(): Promise<Discovery> {
		const outcome = await this.#outcome();
		if (outcome.ok) return outcome.discovery;
		throw outcome.failure;
	}

	authorizationUrl(
		discovery: Discovery,
		{
			redirectUri,
			state,
			nonce,
			codeVerifier
		}: { redirectUri: string; state: string; nonce: string; codeVerifier: string }
	): string {
		const url = new URL(discovery.authorizationEndpoint);
		url.searchParams.set('response_type', 'code');
		url.searchParams.set('client_id', this.#settings.clientId);
		url.searchParams.set('redirect_uri', redirectUri);
		url.searchParams.set('scope', this.#settings.scopes);
		url.searchParams.set('state', state);
		url.searchParams.set('nonce', nonce);
		url.searchParams.set('code_challenge', codeChallenge(codeVerifier));
		url.searchParams.set('code_challenge_method', 'S256');
		return url.href;
	}

	/** Redeem an authorization code; returns the ID token and drops every other token. */
	async redeemCode(
		discovery: Discovery,
		{ code, redirectUri, codeVerifier }: { code: string; redirectUri: string; codeVerifier: string }
	): Promise<string> {
		const body = new URLSearchParams({
			grant_type: 'authorization_code',
			code,
			redirect_uri: redirectUri,
			code_verifier: codeVerifier
		});
		const headers = new Headers({
			accept: 'application/json',
			'content-type': 'application/x-www-form-urlencoded'
		});
		const { clientId, clientSecret } = this.#settings;
		if (clientSecret === null) body.set('client_id', clientId);
		else headers.set('authorization', basicAuthorization(clientId, clientSecret));
		let response: Response;
		let text: string;
		try {
			response = await this.#fetch(discovery.tokenEndpoint, {
				method: 'POST',
				headers,
				body,
				credentials: 'omit',
				redirect: 'error',
				signal: AbortSignal.timeout(this.#timeoutMs)
			});
			text = await response.text();
		} catch {
			throw new SignInError('idp_unavailable', 'the token endpoint did not answer');
		}
		if (response.status >= 500 || (!response.ok && response.status < 400)) {
			throw new SignInError('idp_unavailable', `the token endpoint answered ${response.status}`);
		}
		if (!response.ok) {
			throw new SignInError('idp_error', `the token endpoint answered ${response.status}`);
		}
		const answer = parseJson(text);
		if (!isJsonObject(answer)) throw new SignInError('idp_error', 'the token answer is not JSON');
		const idToken = answer.id_token;
		if (typeof idToken !== 'string' || idToken === '') {
			throw new SignInError('token_rejected', 'the token answer has no id_token');
		}
		return idToken;
	}

	/**
	 * Check the ID token's claims against this sign-in. The signature is not checked here: the
	 * API verifies it during the exchange.
	 */
	checkIdToken(
		idToken: string,
		{ issuer, nonce, nowSeconds }: { issuer: string; nonce: string; nowSeconds: number }
	): void {
		const claims = jwtPayload(idToken);
		const { clientId } = this.#settings;
		if (claims === null) throw new SignInError('token_rejected', 'the ID token is malformed');
		if (claims.iss !== issuer) throw new SignInError('token_rejected', 'iss is not the issuer');
		const aud = claims.aud;
		const audiences = typeof aud === 'string' ? [aud] : Array.isArray(aud) ? aud : [];
		if (!audiences.includes(clientId)) {
			throw new SignInError('token_rejected', 'aud does not contain the client id');
		}
		if ('azp' in claims && claims.azp !== clientId) {
			throw new SignInError('token_rejected', 'azp is not the client id');
		}
		if (typeof claims.nonce !== 'string' || !safeEqual(claims.nonce, nonce)) {
			throw new SignInError('token_rejected', 'nonce does not match');
		}
		if (typeof claims.exp !== 'number' || claims.exp <= nowSeconds) {
			throw new SignInError('token_rejected', 'the ID token has expired');
		}
	}

	#outcome(): Promise<DiscoveryOutcome> {
		const cached = this.#cache;
		if (cached !== undefined && cached.until > this.#now()) return Promise.resolve(cached.outcome);
		this.#inflight ??= this.#load().then((outcome) => {
			const ttl = outcome.ok ? DISCOVERY_TTL_MS : DISCOVERY_FAILURE_TTL_MS;
			this.#cache = { until: this.#now() + ttl, outcome };
			this.#inflight = undefined;
			return outcome;
		});
		return this.#inflight;
	}

	async #load(): Promise<DiscoveryOutcome> {
		try {
			return { ok: true, discovery: await this.#fetchDiscovery() };
		} catch (failure) {
			const signIn =
				failure instanceof SignInError
					? failure
					: new SignInError('idp_unavailable', 'discovery failed');
			return { ok: false, failure: signIn };
		}
	}

	async #fetchDiscovery(): Promise<Discovery> {
		const { issuer } = this.#settings;
		const url = new URL(`${issuer}/.well-known/openid-configuration`);
		let response: Response;
		let text: string;
		try {
			response = await this.#fetch(url, {
				headers: { accept: 'application/json' },
				credentials: 'omit',
				redirect: 'error',
				signal: AbortSignal.timeout(this.#timeoutMs)
			});
			text = await response.text();
		} catch {
			throw new SignInError('idp_unavailable', 'discovery did not answer');
		}
		if (!response.ok) {
			throw new SignInError('idp_unavailable', `discovery answered ${response.status}`);
		}
		const document = parseJson(text);
		if (!isJsonObject(document)) throw new SignInError('idp_unavailable', 'discovery is not JSON');
		if (document.issuer !== issuer) {
			throw new SignInError(
				'config',
				`discovery names the issuer ${describe(document.issuer)}, which is not HURON_WEB_OIDC_ISSUER`
			);
		}
		const methods = document.code_challenge_methods_supported;
		if (Array.isArray(methods) && !methods.includes('S256')) {
			throw new SignInError('config', 'the IdP does not support PKCE S256');
		}
		const authorizationEndpoint = endpoint(document.authorization_endpoint);
		const tokenEndpoint = endpoint(document.token_endpoint);
		if (authorizationEndpoint === null || tokenEndpoint === null) {
			throw new SignInError('config', 'discovery lacks the authorization or token endpoint');
		}
		return {
			issuer,
			authorizationEndpoint,
			tokenEndpoint,
			endSessionEndpoint: endpoint(document.end_session_endpoint)
		};
	}
}

/** Everything the sign-in, callback and logout routes depend on. */
export interface AuthDependencies {
	config: Config;
	oidc: OidcClient;
	sealer: TransactionSealer;
	sessions: SessionStore;
	exchange: (companyToken: string) => Promise<ExchangeOut>;
	now: () => number;
}

/** The part of a request event the auth routes need. */
export interface AuthRequest {
	cookies: Cookies;
	url: URL;
	/** Whether the request already carries a live session. */
	signedIn: boolean;
}

let production: { config: Config; oidc: OidcClient } | undefined;

/** The dependencies of this process. */
export function authDependencies(): AuthDependencies {
	const config = getConfig();
	if (production?.config !== config) {
		production = {
			config,
			oidc: new OidcClient({ settings: config.oidc, timeoutMs: config.apiTimeoutMs })
		};
	}
	return {
		config,
		oidc: production.oidc,
		sealer: transactionSealer(),
		sessions: sessionStore(),
		exchange: (companyToken) =>
			exchange(companyToken, { baseUrl: config.apiUrl, timeoutMs: config.exchangeTimeoutMs }),
		now: Date.now
	};
}

/** `GET /auth/login`: seal a new transaction into its cookie; returns the authorization URL. */
export async function startSignIn(request: AuthRequest, deps: AuthDependencies): Promise<string> {
	const origin = publicOrigin(deps.config, request.url);
	const returnTo = safeReturnTo(request.url.searchParams.get('returnTo'), origin);
	let discovery: Discovery;
	try {
		discovery = await deps.oidc.discover();
	} catch (failure) {
		return failedSignIn(failure, returnTo);
	}
	const jar = new CookieJar(request.cookies, origin);
	const nowSeconds = Math.floor(deps.now() / 1000);
	keepNewestTransactions(jar, deps.sealer, nowSeconds, MAX_TRANSACTIONS - 1);
	const transaction: Transaction = {
		state: randomToken(),
		nonce: randomToken(),
		codeVerifier: randomToken(),
		returnTo,
		exp: nowSeconds + TRANSACTION_MAX_AGE_SECONDS
	};
	jar.setTransaction(transaction.state, deps.sealer.seal(transaction));
	return deps.oidc.authorizationUrl(discovery, {
		redirectUri: callbackUri(origin),
		state: transaction.state,
		nonce: transaction.nonce,
		codeVerifier: transaction.codeVerifier
	});
}

/** `GET /auth/callback`: finish the sign-in and create the session; returns where to go next. */
export async function finishSignIn(request: AuthRequest, deps: AuthDependencies): Promise<string> {
	const origin = publicOrigin(deps.config, request.url);
	const jar = new CookieJar(request.cookies, origin);
	const params = request.url.searchParams;
	const state = params.get('state') ?? '';
	const nowSeconds = Math.floor(deps.now() / 1000);
	const base = state.length >= 8 ? transactionCookieBase(state) : null;
	const cookie = jar.transactions().find((candidate) => candidate.base === base);
	const opened = cookie === undefined ? null : deps.sealer.open(cookie.value, nowSeconds);
	if (cookie !== undefined) jar.delete(cookie.base);
	// Checked again where it is used: a value sealed before the rules changed (a dev reload
	// keeps the key) must not leave the origin either.
	const returnTo = safeReturnTo(opened?.transaction.returnTo, origin);
	if (opened === null || opened.expired) {
		if (request.signedIn) return returnTo;
		return failedSignIn(new SignInError('state_mismatch', 'no open sign-in for this state'), '/');
	}
	const { transaction } = opened;
	try {
		if (!safeEqual(state, transaction.state)) {
			throw new SignInError('state_mismatch', 'the state does not match the sign-in');
		}
		if (params.has('error')) throw new SignInError('idp_error', 'the IdP answered with an error');
		const code = params.get('code');
		if (!code) throw new SignInError('idp_error', 'the IdP answered without a code');
		const discovery = await deps.oidc.discover();
		const redirectUri = callbackUri(origin);
		const idToken = await deps.oidc.redeemCode(discovery, {
			code,
			redirectUri,
			codeVerifier: transaction.codeVerifier
		});
		deps.oidc.checkIdToken(idToken, {
			issuer: discovery.issuer,
			nonce: transaction.nonce,
			nowSeconds
		});
		const exchanged = await exchangeIdToken(deps, idToken);
		const previous = jar.session();
		if (previous !== undefined) deps.sessions.delete(previous);
		const session = createSession(deps.sessions, exchanged);
		jar.setSession(session.id, session.maxAgeSeconds);
	} catch (failure) {
		return failedSignIn(failure, returnTo);
	}
	return returnTo;
}

/** `POST /logout`: end the session; returns the IdP's logout URL or the signed-out login page. */
export async function signOut(request: AuthRequest, deps: AuthDependencies): Promise<string> {
	const origin = publicOrigin(deps.config, request.url);
	const jar = new CookieJar(request.cookies, origin);
	const sessionId = jar.session();
	if (sessionId !== undefined) deps.sessions.delete(sessionId);
	jar.deleteSession();
	const signedOut = loginPath({ status: 'signed-out' });
	if (!deps.config.oidc.logout) return signedOut;
	let discovery: Discovery;
	try {
		discovery = await deps.oidc.discover();
	} catch {
		return signedOut;
	}
	if (discovery.endSessionEndpoint === null) return signedOut;
	const url = new URL(discovery.endSessionEndpoint);
	url.searchParams.set('client_id', deps.config.oidc.clientId);
	url.searchParams.set('post_logout_redirect_uri', `${origin}${signedOut}`);
	return url.href;
}

function callbackUri(origin: string): string {
	return `${origin}/auth/callback`;
}

function keepNewestTransactions(
	jar: CookieJar,
	sealer: TransactionSealer,
	nowSeconds: number,
	keep: number
): void {
	const live: Array<{ base: string; exp: number }> = [];
	for (const cookie of jar.transactions()) {
		const opened = sealer.open(cookie.value, nowSeconds);
		if (opened === null || opened.expired) jar.delete(cookie.base);
		else live.push({ base: cookie.base, exp: opened.transaction.exp });
	}
	live.sort((a, b) => a.exp - b.exp);
	for (const stale of live.slice(0, Math.max(0, live.length - keep))) jar.delete(stale.base);
}

async function exchangeIdToken(deps: AuthDependencies, idToken: string): Promise<ExchangeOut> {
	try {
		return await deps.exchange(idToken);
	} catch (failure) {
		if (failure instanceof HuronApiError) {
			if (failure.status === 503 && failure.code === 'GROUP_DIRECTORY_UNAVAILABLE') {
				throw new SignInError('groups_unavailable', 'the group directory is unavailable');
			}
			if (failure.status >= 400 && failure.status < 500) {
				throw new SignInError(
					'token_rejected',
					`the exchange answered ${failure.status} ${failure.code}`
				);
			}
		}
		throw new SignInError('service_unavailable', 'the exchange failed');
	}
}

function createSession(
	sessions: SessionStore,
	exchanged: ExchangeOut
): { id: string; maxAgeSeconds: number } {
	try {
		return sessions.create({
			huronToken: exchanged.huron_token,
			tokenExpiresAt: exchanged.expires_at,
			subject: exchanged.subject,
			name: exchanged.name,
			groups: exchanged.groups
		});
	} catch (failure) {
		if (failure instanceof SessionError) {
			throw new SignInError('service_unavailable', `no session: ${failure.message}`);
		}
		throw failure;
	}
}

function failedSignIn(failure: unknown, returnTo: string): string {
	let signIn: SignInError;
	if (failure instanceof SignInError) {
		signIn = failure;
	} else {
		console.error('huron-web sign-in failed unexpectedly', failure);
		signIn = new SignInError('service_unavailable', 'unexpected failure');
	}
	const log = signIn.code === 'config' ? console.error : console.warn;
	log(`huron-web sign-in failed: ${signIn.message}`);
	return loginPath({ error: signIn.code, returnTo: returnTo === '/' ? undefined : returnTo });
}

function transactionFrom(value: JsonValue | undefined): Transaction | null {
	if (!isJsonObject(value)) return null;
	const { state, nonce, codeVerifier, returnTo, exp } = value;
	if (
		typeof state !== 'string' ||
		typeof nonce !== 'string' ||
		typeof codeVerifier !== 'string' ||
		typeof returnTo !== 'string' ||
		typeof exp !== 'number'
	) {
		return null;
	}
	return { state, nonce, codeVerifier, returnTo, exp };
}

function jwtPayload(token: string): Record<string, JsonValue> | null {
	const parts = token.split('.');
	if (parts.length !== 3 || !/^[A-Za-z0-9_-]+$/.test(parts[1])) return null;
	const claims = parseJson(Buffer.from(parts[1], 'base64url').toString('utf8'));
	return isJsonObject(claims) ? claims : null;
}

function endpoint(value: JsonValue | undefined): string | null {
	if (typeof value !== 'string') return null;
	try {
		const url = new URL(value);
		return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
	} catch {
		return null;
	}
}

function basicAuthorization(clientId: string, clientSecret: string): string {
	const credentials = `${formEncode(clientId)}:${formEncode(clientSecret)}`;
	return `Basic ${Buffer.from(credentials, 'utf8').toString('base64')}`;
}

/** RFC 6749 section 2.3.1: client credentials are form-encoded before Basic encoding. */
function formEncode(value: string): string {
	return new URLSearchParams({ value }).toString().slice('value='.length);
}

function describe(value: JsonValue | undefined): string {
	const text = JSON.stringify(value) ?? 'nothing';
	return text.length > 200 ? `${text.slice(0, 200)}…` : text;
}
