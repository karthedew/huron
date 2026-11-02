// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ExchangeOut } from '$api/openapi';
import {
	connectionReset,
	fakeFetch,
	hangingAnswer,
	jsonResponse,
	problemResponse,
	type FetchCall
} from '$lib/testing/api-fixtures';
import { FakeCookies } from '$lib/testing/fake-cookies';
import type { Config } from './config';
import { HuronApiError } from './huron-api';
import {
	DISCOVERY_FAILURE_TTL_MS,
	DISCOVERY_TTL_MS,
	OidcClient,
	SignInError,
	TransactionSealer,
	codeChallenge,
	finishSignIn,
	randomToken,
	safeEqual,
	signOut,
	startSignIn,
	type AuthDependencies,
	type Discovery,
	type Transaction
} from './oidc';
import { createSessionStore, type SessionStore } from './sessions';

const ISSUER = 'http://127.0.0.1:8199';
const ORIGIN = 'http://localhost:4173';
const NOW = Date.parse('2026-10-29T10:00:00Z');
const NOW_SECONDS = NOW / 1000;
const KEY = new Uint8Array(32).fill(7);

const CONFIG: Config = {
	origin: ORIGIN,
	apiUrl: 'http://127.0.0.1:8197',
	oidc: {
		issuer: ISSUER,
		clientId: 'huron-web',
		clientSecret: 'e2e-secret',
		scopes: 'openid profile email',
		logout: true
	},
	mountPrefix: '/projects/huron',
	apiTimeoutMs: 1000,
	exchangeTimeoutMs: 35_000
};

const DISCOVERY_DOCUMENT = {
	issuer: ISSUER,
	authorization_endpoint: `${ISSUER}/authorize?prompt=login`,
	token_endpoint: `${ISSUER}/token`,
	end_session_endpoint: `${ISSUER}/logout`,
	jwks_uri: `${ISSUER}/jwks`,
	code_challenge_methods_supported: ['S256']
};

const DISCOVERY: Discovery = {
	issuer: ISSUER,
	authorizationEndpoint: `${ISSUER}/authorize?prompt=login`,
	tokenEndpoint: `${ISSUER}/token`,
	endSessionEndpoint: `${ISSUER}/logout`
};

const EXCHANGED: ExchangeOut = {
	huron_token: 'huron-token-for-erin',
	expires_at: '2026-10-29T18:00:00Z',
	subject: 'sub-erin',
	name: 'Erin Example',
	groups: ['helio-readers']
};

function base64url(value: unknown): string {
	return Buffer.from(JSON.stringify(value)).toString('base64url');
}

function idToken(claims: Record<string, unknown>): string {
	return `${base64url({ alg: 'RS256', typ: 'JWT', kid: 'k1' })}.${base64url(claims)}.c2lnbmF0dXJl`;
}

function claims(nonce: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
	return {
		iss: ISSUER,
		aud: ['huron-web', 'huron-cli'],
		azp: 'huron-web',
		sub: 'sub-erin',
		nonce,
		iat: NOW_SECONDS,
		exp: NOW_SECONDS + 300,
		...overrides
	};
}

interface FakeIdp {
	fetch: typeof fetch;
	calls: FetchCall[];
	/** Claims of the next ID token; the nonce of the current sign-in is filled in. */
	claims: (nonce: string) => Record<string, unknown>;
	tokenAnswer: (call: FetchCall, nonce: string) => Response;
	nonce: string;
	discovery: () => Response;
}

function fakeIdp(): FakeIdp {
	const idp: FakeIdp = {
		fetch: globalThis.fetch,
		calls: [],
		claims: (nonce) => claims(nonce),
		tokenAnswer: (_, nonce) =>
			jsonResponse({
				id_token: idToken(idp.claims(nonce)),
				access_token: 'access-token',
				refresh_token: 'refresh-token',
				token_type: 'Bearer'
			}),
		nonce: '',
		discovery: () => jsonResponse(DISCOVERY_DOCUMENT)
	};
	const fake = fakeFetch((call) => {
		if (call.url === `${ISSUER}/.well-known/openid-configuration`) return idp.discovery();
		if (call.url === `${ISSUER}/token`) return idp.tokenAnswer(call, idp.nonce);
		throw new Error(`unexpected request to ${call.url}`);
	});
	idp.fetch = fake.fetch;
	idp.calls = fake.calls;
	return idp;
}

interface Harness {
	idp: FakeIdp;
	cookies: FakeCookies;
	sessions: SessionStore;
	exchanged: string[];
	deps: AuthDependencies;
	clock: { now: number };
}

function harness(
	options: { config?: Config; exchange?: (token: string) => Promise<ExchangeOut> } = {}
): Harness {
	const idp = fakeIdp();
	const clock = { now: NOW };
	const sessions = createSessionStore({ now: () => clock.now });
	const exchanged: string[] = [];
	const config = options.config ?? CONFIG;
	const deps: AuthDependencies = {
		config,
		oidc: new OidcClient({
			settings: config.oidc,
			timeoutMs: 1000,
			fetch: idp.fetch,
			now: () => clock.now
		}),
		sealer: new TransactionSealer(KEY),
		sessions,
		exchange:
			options.exchange ??
			(async (token) => {
				exchanged.push(token);
				return EXCHANGED;
			}),
		now: () => clock.now
	};
	return { idp, cookies: new FakeCookies(), sessions, exchanged, deps, clock };
}

function request(h: Harness, path: string, signedIn = false) {
	return { cookies: h.cookies, url: new URL(path, ORIGIN), signedIn };
}

/** Start a sign-in and return the authorization request's parameters. */
async function begin(h: Harness, returnTo = '/orgs/helio') {
	const location = await startSignIn(
		request(h, `/auth/login?returnTo=${encodeURIComponent(returnTo)}`),
		h.deps
	);
	const url = new URL(location);
	const state = url.searchParams.get('state') ?? '';
	h.idp.nonce = url.searchParams.get('nonce') ?? '';
	return { url, state };
}

function callback(h: Harness, query: Record<string, string>, signedIn = false) {
	return finishSignIn(request(h, `/auth/callback?${new URLSearchParams(query)}`, signedIn), h.deps);
}

function transaction(overrides: Partial<Transaction> = {}): Transaction {
	return {
		state: randomToken(),
		nonce: randomToken(),
		codeVerifier: randomToken(),
		returnTo: '/orgs/helio',
		exp: NOW_SECONDS + 600,
		...overrides
	};
}

/** The code of the SignInError `run` throws. */
function rejection(run: () => void): string {
	try {
		run();
	} catch (error) {
		if (error instanceof SignInError) return error.code;
		throw error;
	}
	throw new Error('expected a SignInError');
}

beforeEach(() => {
	vi.spyOn(console, 'warn').mockImplementation(() => undefined);
	vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
	vi.restoreAllMocks();
});

describe('TransactionSealer', () => {
	it('round-trips a transaction without exposing it', () => {
		const sealer = new TransactionSealer(KEY);
		const value = transaction();
		const sealed = sealer.seal(value);
		expect(sealed).toMatch(/^[A-Za-z0-9_-]+$/);
		for (const secret of [value.state, value.nonce, value.codeVerifier]) {
			expect(sealed).not.toContain(secret);
		}
		expect(sealer.open(sealed, NOW_SECONDS)).toEqual({ transaction: value, expired: false });
		expect(sealer.seal(value)).not.toBe(sealed);
	});

	it('marks a transaction past its exp as expired', () => {
		const sealer = new TransactionSealer(KEY);
		const sealed = sealer.seal(transaction({ exp: NOW_SECONDS }));
		expect(sealer.open(sealed, NOW_SECONDS)?.expired).toBe(true);
		expect(sealer.open(sealed, NOW_SECONDS - 1)?.expired).toBe(false);
	});

	it('refuses values sealed with another key, tampered values and garbage', () => {
		const sealer = new TransactionSealer(KEY);
		const sealed = sealer.seal(transaction());
		const other = new TransactionSealer(new Uint8Array(32).fill(8));
		expect(other.open(sealed, NOW_SECONDS)).toBeNull();
		const bytes = Buffer.from(sealed, 'base64url');
		bytes[20] ^= 1;
		expect(sealer.open(bytes.toString('base64url'), NOW_SECONDS)).toBeNull();
		for (const garbage of ['', 'a', 'not base64!', Buffer.alloc(28).toString('base64url')]) {
			expect(sealer.open(garbage, NOW_SECONDS)).toBeNull();
		}
	});

	it('requires a 256-bit key', () => {
		expect(() => new TransactionSealer(new Uint8Array(16))).toThrow(RangeError);
	});
});

describe('PKCE and comparisons', () => {
	it('makes 43-character random tokens', () => {
		const token = randomToken();
		expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/);
		expect(randomToken()).not.toBe(token);
	});

	it('derives the S256 challenge of RFC 7636 appendix B', () => {
		expect(codeChallenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk')).toBe(
			'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'
		);
	});

	it('compares strings of any length safely', () => {
		expect(safeEqual('abc', 'abc')).toBe(true);
		expect(safeEqual('abc', 'abd')).toBe(false);
		expect(safeEqual('abc', 'abcd')).toBe(false);
		expect(safeEqual('', '')).toBe(true);
	});
});

describe('OidcClient.discover', () => {
	function discoveringClient(...answers: Parameters<typeof fakeFetch>) {
		const fake = fakeFetch(...answers);
		const clock = { now: NOW };
		const client = new OidcClient({
			settings: CONFIG.oidc,
			timeoutMs: 50,
			fetch: fake.fetch,
			now: () => clock.now
		});
		return { client, calls: fake.calls, clock };
	}

	async function discoveryError(client: OidcClient): Promise<SignInError> {
		try {
			await client.discover();
		} catch (error) {
			if (error instanceof SignInError) return error;
			throw error;
		}
		throw new Error('expected a SignInError');
	}

	it('reads the endpoints from the well-known document and caches them for an hour', async () => {
		const { client, calls, clock } = discoveringClient(jsonResponse(DISCOVERY_DOCUMENT));
		expect(await client.discover()).toEqual(DISCOVERY);
		expect(calls[0].url).toBe(`${ISSUER}/.well-known/openid-configuration`);
		expect(calls[0].init).toMatchObject({ credentials: 'omit', redirect: 'error' });
		clock.now += DISCOVERY_TTL_MS - 1;
		await client.discover();
		expect(calls).toHaveLength(1);
		clock.now += 1;
		await client.discover();
		expect(calls).toHaveLength(2);
	});

	it('shares one request between concurrent callers', async () => {
		const { client, calls } = discoveringClient(jsonResponse(DISCOVERY_DOCUMENT));
		await Promise.all([client.discover(), client.discover(), client.discover()]);
		expect(calls).toHaveLength(1);
	});

	it('works without an end_session_endpoint', async () => {
		const { end_session_endpoint: _, ...document } = DISCOVERY_DOCUMENT;
		const { client } = discoveringClient(jsonResponse(document));
		expect((await client.discover()).endSessionEndpoint).toBeNull();
	});

	it('caches failures for five seconds', async () => {
		const { client, calls, clock } = discoveringClient(
			new TypeError('fetch failed'),
			jsonResponse(DISCOVERY_DOCUMENT)
		);
		expect((await discoveryError(client)).code).toBe('idp_unavailable');
		clock.now += DISCOVERY_FAILURE_TTL_MS - 1;
		expect((await discoveryError(client)).code).toBe('idp_unavailable');
		expect(calls).toHaveLength(1);
		clock.now += 1;
		expect(await client.discover()).toEqual(DISCOVERY);
	});

	it.each([
		['a network failure', new TypeError('fetch failed')],
		['an error status', jsonResponse(DISCOVERY_DOCUMENT, 503)],
		['a document that is not JSON', new Response('<html>', { status: 200 })]
	])('reports %s as idp_unavailable', async (_, answer) => {
		const { client } = discoveringClient(answer);
		expect((await discoveryError(client)).code).toBe('idp_unavailable');
	});

	it('reports a timeout as idp_unavailable', async () => {
		const { client } = discoveringClient(hangingAnswer);
		expect((await discoveryError(client)).code).toBe('idp_unavailable');
	});

	it.each([
		['another issuer', { ...DISCOVERY_DOCUMENT, issuer: `${ISSUER}/` }],
		['no issuer', { ...DISCOVERY_DOCUMENT, issuer: undefined }],
		['no token endpoint', { ...DISCOVERY_DOCUMENT, token_endpoint: undefined }],
		[
			'a non-http authorization endpoint',
			{ ...DISCOVERY_DOCUMENT, authorization_endpoint: 'javascript:x' }
		],
		['no PKCE S256', { ...DISCOVERY_DOCUMENT, code_challenge_methods_supported: ['plain'] }]
	])('reports a document with %s as a configuration error', async (_, document) => {
		const { client } = discoveringClient(jsonResponse(document));
		const error = await discoveryError(client);
		expect(error.code).toBe('config');
	});
});

describe('OidcClient requests', () => {
	it('builds the authorization URL on the advertised endpoint, keeping its query', () => {
		const client = new OidcClient({ settings: CONFIG.oidc, timeoutMs: 1000 });
		const url = new URL(
			client.authorizationUrl(DISCOVERY, {
				redirectUri: `${ORIGIN}/auth/callback`,
				state: 'the-state',
				nonce: 'the-nonce',
				codeVerifier: 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
			})
		);
		expect(url.origin + url.pathname).toBe(`${ISSUER}/authorize`);
		expect(Object.fromEntries(url.searchParams)).toEqual({
			prompt: 'login',
			response_type: 'code',
			client_id: 'huron-web',
			redirect_uri: `${ORIGIN}/auth/callback`,
			scope: 'openid profile email',
			state: 'the-state',
			nonce: 'the-nonce',
			code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
			code_challenge_method: 'S256'
		});
	});

	function redeeming(answer: Parameters<typeof fakeFetch>[0], clientSecret: string | null) {
		const fake = fakeFetch(answer);
		const client = new OidcClient({
			settings: { ...CONFIG.oidc, clientSecret },
			timeoutMs: 50,
			fetch: fake.fetch
		});
		const redeem = () =>
			client.redeemCode(DISCOVERY, {
				code: 'the-code',
				redirectUri: `${ORIGIN}/auth/callback`,
				codeVerifier: 'the-verifier'
			});
		return { redeem, calls: fake.calls };
	}

	async function redeemError(redeem: () => Promise<string>): Promise<string> {
		try {
			await redeem();
		} catch (error) {
			if (error instanceof SignInError) return error.code;
			throw error;
		}
		throw new Error('expected a SignInError');
	}

	it('redeems the code as a confidential client with client_secret_basic', async () => {
		const { redeem, calls } = redeeming(
			jsonResponse({ id_token: 'the-id-token', access_token: 'a', refresh_token: 'r' }),
			'sec:ret/+'
		);
		expect(await redeem()).toBe('the-id-token');
		const init = calls[0].init;
		expect(calls[0].url).toBe(`${ISSUER}/token`);
		expect(init).toMatchObject({ method: 'POST', credentials: 'omit', redirect: 'error' });
		expect(Object.fromEntries(new URLSearchParams(String(init?.body)))).toEqual({
			grant_type: 'authorization_code',
			code: 'the-code',
			redirect_uri: `${ORIGIN}/auth/callback`,
			code_verifier: 'the-verifier'
		});
		const authorization = new Headers(init?.headers).get('authorization') ?? '';
		expect(Buffer.from(authorization.replace('Basic ', ''), 'base64').toString()).toBe(
			'huron-web:sec%3Aret%2F%2B'
		);
	});

	it('sends the client id in the body as a public client', async () => {
		const { redeem, calls } = redeeming(jsonResponse({ id_token: 'the-id-token' }), null);
		await redeem();
		const init = calls[0].init;
		expect(new URLSearchParams(String(init?.body)).get('client_id')).toBe('huron-web');
		expect(new Headers(init?.headers).has('authorization')).toBe(false);
	});

	it.each([
		['a network failure', new TypeError('fetch failed'), 'idp_unavailable'],
		['a connection reset', connectionReset(), 'idp_unavailable'],
		['a server error', jsonResponse({ error: 'temporarily_unavailable' }, 503), 'idp_unavailable'],
		['a rejected code', jsonResponse({ error: 'invalid_grant' }, 400), 'idp_error'],
		['an answer that is not JSON', new Response('ok', { status: 200 }), 'idp_error'],
		['an answer without id_token', jsonResponse({ access_token: 'a' }), 'token_rejected']
	])('reports %s', async (_, answer, code) => {
		const { redeem } = redeeming(answer, 'secret');
		expect(await redeemError(redeem)).toBe(code);
	});

	it('reports a timeout as idp_unavailable', async () => {
		const { redeem } = redeeming(hangingAnswer, 'secret');
		expect(await redeemError(redeem)).toBe('idp_unavailable');
	});
});

describe('OidcClient.checkIdToken', () => {
	const client = new OidcClient({ settings: CONFIG.oidc, timeoutMs: 1000 });
	const check = (token: string) =>
		client.checkIdToken(token, { issuer: ISSUER, nonce: 'n', nowSeconds: NOW_SECONDS });

	it('accepts a token for this client and sign-in', () => {
		expect(() => check(idToken(claims('n')))).not.toThrow();
		expect(() => check(idToken(claims('n', { aud: 'huron-web', azp: undefined })))).not.toThrow();
	});

	it.each([
		['another issuer', claims('n', { iss: `${ISSUER}/` })],
		['an audience without this client', claims('n', { aud: ['huron-cli'] })],
		['a string audience for another client', claims('n', { aud: 'huron-cli' })],
		['no audience', claims('n', { aud: undefined })],
		['another authorized party', claims('n', { azp: 'huron-cli' })],
		['another nonce', claims('m')],
		['no nonce', claims('n', { nonce: undefined })],
		['an expired token', claims('n', { exp: NOW_SECONDS })],
		['no expiry', claims('n', { exp: undefined })]
	])('rejects %s', (_, payload) => {
		expect(rejection(() => check(idToken(payload)))).toBe('token_rejected');
	});

	it.each([
		'',
		'a.b',
		'a.b.c.d',
		'a.!!!.c',
		`a.${Buffer.from('not json').toString('base64url')}.c`
	])('rejects the malformed token %j', (token) => {
		expect(rejection(() => check(token))).toBe('token_rejected');
	});
});

describe('startSignIn', () => {
	it('seals a transaction into a cookie named by its state and redirects to the IdP', async () => {
		const h = harness();
		const { url, state } = await begin(h, '/catalogs/heliophysics?x=1');
		expect(url.origin + url.pathname).toBe(`${ISSUER}/authorize`);
		expect(url.searchParams.get('redirect_uri')).toBe(`${ORIGIN}/auth/callback`);
		expect(state).toMatch(/^[A-Za-z0-9_-]{43}$/);
		const write = h.cookies.lastWrite(`huron_oidc_${state.slice(0, 8)}`);
		expect(write?.options).toEqual({
			path: '/',
			httpOnly: true,
			sameSite: 'lax',
			secure: false,
			maxAge: 600
		});
		const opened = h.deps.sealer.open(write?.value ?? '', NOW_SECONDS);
		expect(opened?.transaction).toMatchObject({
			state,
			nonce: url.searchParams.get('nonce'),
			returnTo: '/catalogs/heliophysics?x=1',
			exp: NOW_SECONDS + 600
		});
		expect(url.searchParams.get('code_challenge')).toBe(
			codeChallenge(opened?.transaction.codeVerifier ?? '')
		);
	});

	it('canonicalizes returnTo before sealing it', async () => {
		const h = harness();
		const { state } = await begin(h, '//evil.com/x');
		const value = h.cookies.get(`huron_oidc_${state.slice(0, 8)}`) ?? '';
		expect(h.deps.sealer.open(value, NOW_SECONDS)?.transaction.returnTo).toBe('/');
	});

	it('names cookies with __Host- on https', async () => {
		const h = harness({ config: { ...CONFIG, origin: 'https://huron.example.org' } });
		const { state, url } = await begin(h);
		expect(h.cookies.get(`__Host-huron_oidc_${state.slice(0, 8)}`)).toBeDefined();
		expect(url.searchParams.get('redirect_uri')).toBe('https://huron.example.org/auth/callback');
	});

	it('keeps at most three sign-ins in flight, dropping the oldest and unreadable ones', async () => {
		const h = harness();
		h.cookies.values.set('huron_oidc_garbage0', 'not-sealed');
		const states: string[] = [];
		for (let index = 0; index < 4; index += 1) {
			h.clock.now += 1000;
			states.push((await begin(h)).state);
		}
		const names = h.cookies.getAll().map(({ name }) => name);
		expect(names.filter((name) => name.startsWith('huron_oidc_')).sort()).toEqual(
			states
				.slice(1)
				.map((state) => `huron_oidc_${state.slice(0, 8)}`)
				.sort()
		);
	});

	it.each([
		['the IdP is unreachable', () => new Response(null, { status: 503 }), 'idp_unavailable'],
		[
			'discovery names another issuer',
			() => jsonResponse({ ...DISCOVERY_DOCUMENT, issuer: 'x' }),
			'config'
		]
	])('sends the user back to the login page when %s', async (_, discovery, code) => {
		const h = harness();
		h.idp.discovery = discovery;
		const location = await startSignIn(request(h, '/auth/login?returnTo=%2Forgs%2Fhelio'), h.deps);
		expect(location).toBe(`/login?error=${code}&returnTo=%2Forgs%2Fhelio`);
		expect(h.cookies.writes).toEqual([]);
	});

	it('leaves returnTo out of the error redirect when it is the default', async () => {
		const h = harness();
		h.idp.discovery = () => new Response(null, { status: 500 });
		expect(await startSignIn(request(h, '/auth/login'), h.deps)).toBe(
			'/login?error=idp_unavailable'
		);
	});
});

describe('finishSignIn', () => {
	it('creates a session from the exchange and continues at returnTo', async () => {
		const h = harness();
		const old = h.sessions.create({
			...EXCHANGED,
			huronToken: 'old',
			tokenExpiresAt: EXCHANGED.expires_at
		});
		h.cookies.values.set('huron_session', old.id);
		const { state } = await begin(h);
		const location = await callback(h, { code: 'the-code', state });
		expect(location).toBe('/orgs/helio');
		expect(h.exchanged).toEqual([idToken(claims(h.idp.nonce))]);
		const sessionId = h.cookies.get('huron_session') ?? '';
		expect(sessionId).not.toBe(old.id);
		expect(h.sessions.user(sessionId)).toMatchObject({
			subject: 'sub-erin',
			groups: ['helio-readers']
		});
		expect(h.sessions.token(sessionId)).toBe('huron-token-for-erin');
		expect(h.sessions.user(old.id)).toBeUndefined();
		expect(h.cookies.lastWrite('huron_session')?.options).toMatchObject({
			httpOnly: true,
			sameSite: 'lax',
			secure: false,
			maxAge: 8 * 3600 - 30
		});
		expect(h.cookies.get(`huron_oidc_${state.slice(0, 8)}`)).toBeUndefined();
		const tokenCall = h.idp.calls.find((call) => call.url === `${ISSUER}/token`);
		expect(new URLSearchParams(String(tokenCall?.init?.body)).get('redirect_uri')).toBe(
			`${ORIGIN}/auth/callback`
		);
	});

	it('finishes interleaved sign-ins independently', async () => {
		const h = harness();
		const first = await begin(h, '/orgs/helio');
		const firstNonce = h.idp.nonce;
		const second = await begin(h, '/orgs/geo');
		expect(await callback(h, { code: 'c2', state: second.state })).toBe('/orgs/geo');
		h.idp.nonce = firstNonce;
		expect(await callback(h, { code: 'c1', state: first.state })).toBe('/orgs/helio');
		expect(h.exchanged).toHaveLength(2);
	});

	it.each([
		['no state', {}],
		['an unknown state', { code: 'c', state: randomToken() }],
		['a short state', { code: 'c', state: 'abc' }]
	])('rejects a callback with %s as state_mismatch', async (_, query) => {
		const h = harness();
		await begin(h);
		expect(await callback(h, query)).toBe('/login?error=state_mismatch');
		expect(h.exchanged).toEqual([]);
	});

	it('rejects a state that only shares the cookie prefix', async () => {
		const h = harness();
		const { state } = await begin(h);
		const forged = `${state.slice(0, 8)}${'A'.repeat(35)}`;
		expect(await callback(h, { code: 'c', state: forged })).toBe(
			'/login?error=state_mismatch&returnTo=%2Forgs%2Fhelio'
		);
		expect(h.cookies.get(`huron_oidc_${state.slice(0, 8)}`)).toBeUndefined();
	});

	it('rejects an expired transaction', async () => {
		const h = harness();
		const { state } = await begin(h);
		h.clock.now += 601_000;
		expect(await callback(h, { code: 'c', state })).toBe('/login?error=state_mismatch');
	});

	it('sends a browser that is already signed in on instead of failing', async () => {
		const h = harness();
		const { state } = await begin(h, '/orgs/geo');
		h.clock.now += 601_000;
		expect(await callback(h, { code: 'c', state }, true)).toBe('/orgs/geo');
		expect(await callback(h, { code: 'c', state: randomToken() }, true)).toBe('/');
	});

	it.each(['/..//evil.com', '/.//evil.com/phish', '/%2e//evil.com', '/x/..//evil.com'])(
		'continues on the origin after a sign-in that asked for %j',
		async (returnTo) => {
			const h = harness();
			const { state } = await begin(h, returnTo);
			expect(await callback(h, { code: 'c', state })).toBe('/');
			expect(h.cookies.get('huron_session')).toBeDefined();
		}
	);

	it('never continues outside the origin, even with a sealed returnTo', async () => {
		const h = harness();
		const seal = (overrides: Partial<Transaction>) => {
			const sealed = transaction(overrides);
			h.cookies.values.set(`huron_oidc_${sealed.state.slice(0, 8)}`, h.deps.sealer.seal(sealed));
			h.idp.nonce = sealed.nonce;
			return sealed.state;
		};
		expect(await callback(h, { code: 'c', state: seal({ returnTo: '//evil.com/phish' }) })).toBe(
			'/'
		);
		expect(h.cookies.get('huron_session')).toBeDefined();
		expect(
			await callback(h, { error: 'access_denied', state: seal({ returnTo: '//evil.com' }) })
		).toBe('/login?error=idp_error');
		const expired = seal({ returnTo: '/..//evil.com', exp: NOW_SECONDS - 1 });
		expect(await callback(h, { code: 'c', state: expired }, true)).toBe('/');
	});

	it.each([
		['an IdP error', { error: 'access_denied' }, 'idp_error'],
		['a missing code', {}, 'idp_error']
	])('reports %s', async (_, extra, code) => {
		const h = harness();
		const { state } = await begin(h);
		expect(await callback(h, { state, ...extra })).toBe(
			`/login?error=${code}&returnTo=%2Forgs%2Fhelio`
		);
	});

	it.each([
		['the token endpoint is down', () => jsonResponse({}, 503), 'idp_unavailable'],
		[
			'the token endpoint refuses the code',
			() => jsonResponse({ error: 'invalid_grant' }, 400),
			'idp_error'
		]
	])('reports when %s', async (_, answer, code) => {
		const h = harness();
		h.idp.tokenAnswer = answer;
		const { state } = await begin(h);
		expect(await callback(h, { code: 'c', state })).toBe(
			`/login?error=${code}&returnTo=%2Forgs%2Fhelio`
		);
	});

	it.each([
		['iss', { iss: 'http://elsewhere' }],
		['aud', { aud: ['huron-cli'] }],
		['azp', { azp: 'huron-cli' }],
		['nonce', { nonce: 'another' }],
		['exp', { exp: NOW_SECONDS - 1 }]
	])('rejects an ID token with a wrong %s before the exchange', async (_, overrides) => {
		const h = harness();
		h.idp.claims = (nonce) => claims(nonce, overrides);
		const { state } = await begin(h);
		expect(await callback(h, { code: 'c', state })).toBe(
			'/login?error=token_rejected&returnTo=%2Forgs%2Fhelio'
		);
		expect(h.exchanged).toEqual([]);
	});

	it.each([
		['a 401', problemResponse(401, 'TOKEN_INVALID'), 'token_rejected'],
		['a 422', problemResponse(422, 'REQUEST_INVALID'), 'token_rejected'],
		[
			'an unavailable group directory',
			problemResponse(503, 'GROUP_DIRECTORY_UNAVAILABLE'),
			'groups_unavailable'
		],
		[
			'another unavailable dependency',
			problemResponse(503, 'DEPENDENCY_UNAVAILABLE'),
			'service_unavailable'
		],
		['an internal error', problemResponse(500, 'INTERNAL'), 'service_unavailable']
	])('maps an exchange answering %s', async (_, response, code) => {
		const failure = new HuronApiError({
			status: response.status,
			code: (await response.json()).code,
			title: 'x'
		});
		const h = harness({
			exchange: async () => {
				throw failure;
			}
		});
		const { state } = await begin(h);
		expect(await callback(h, { code: 'c', state })).toBe(
			`/login?error=${code}&returnTo=%2Forgs%2Fhelio`
		);
		expect(h.cookies.get('huron_session')).toBeUndefined();
	});

	it('maps an unreachable API to service_unavailable', async () => {
		const h = harness({
			exchange: async () => {
				throw new HuronApiError({ status: 503, code: 'API_UNREACHABLE', title: 'x' });
			}
		});
		const { state } = await begin(h);
		expect(await callback(h, { code: 'c', state })).toBe(
			'/login?error=service_unavailable&returnTo=%2Forgs%2Fhelio'
		);
	});

	it('maps a full session store to service_unavailable', async () => {
		const h = harness();
		const full = createSessionStore({ maxTotal: 1, now: () => NOW });
		full.create({
			...EXCHANGED,
			subject: 'someone',
			huronToken: 't',
			tokenExpiresAt: EXCHANGED.expires_at
		});
		h.deps.sessions = full;
		const { state } = await begin(h);
		expect(await callback(h, { code: 'c', state })).toBe(
			'/login?error=service_unavailable&returnTo=%2Forgs%2Fhelio'
		);
	});

	it('logs failures without tokens, codes or verifiers', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
		const h = harness();
		h.idp.claims = (nonce) => claims(nonce, { aud: ['huron-cli'] });
		const { state } = await begin(h);
		await callback(h, { code: 'secret-code', state });
		const logged = JSON.stringify(warn.mock.calls);
		expect(logged).toContain('token_rejected');
		for (const secret of ['secret-code', state, h.idp.nonce, 'e2e-secret']) {
			expect(logged).not.toContain(secret);
		}
	});
});

describe('signOut', () => {
	it('ends the session and continues to the IdP logout without an ID token', async () => {
		const h = harness();
		const session = h.sessions.create({
			...EXCHANGED,
			huronToken: 't',
			tokenExpiresAt: EXCHANGED.expires_at
		});
		h.cookies.values.set('huron_session', session.id);
		const location = new URL(await signOut(request(h, '/logout', true), h.deps));
		expect(location.origin + location.pathname).toBe(`${ISSUER}/logout`);
		expect(Object.fromEntries(location.searchParams)).toEqual({
			client_id: 'huron-web',
			post_logout_redirect_uri: `${ORIGIN}/login?status=signed-out`
		});
		expect(h.sessions.user(session.id)).toBeUndefined();
		expect(h.cookies.lastWrite('huron_session')?.value).toBeNull();
	});

	it('stays local when logout redirects are off', async () => {
		const h = harness({ config: { ...CONFIG, oidc: { ...CONFIG.oidc, logout: false } } });
		expect(await signOut(request(h, '/logout'), h.deps)).toBe('/login?status=signed-out');
		expect(h.idp.calls).toEqual([]);
	});

	it('stays local when the IdP is unavailable or advertises no logout endpoint', async () => {
		const down = harness();
		down.idp.discovery = () => new Response(null, { status: 503 });
		expect(await signOut(request(down, '/logout'), down.deps)).toBe('/login?status=signed-out');
		const { end_session_endpoint: _, ...document } = DISCOVERY_DOCUMENT;
		const silent = harness();
		silent.idp.discovery = () => jsonResponse(document);
		expect(await signOut(request(silent, '/logout'), silent.deps)).toBe('/login?status=signed-out');
	});
});
