/**
 * A dependency-free stand-in for the company OIDC provider and its LDAP group directory, plus a
 * fault proxy in front of the Huron API: one process, two ports. The e2e tests and
 * `npm run demo` run it; as a program it reads the `HURON_E2E_*` ports of `stack.mjs`.
 *
 * IdP, at the issuer (`http://127.0.0.1:8199` by default):
 * - `GET /.well-known/openid-configuration` and `GET /jwks`: an RS256 signing key and, as
 *   Keycloak publishes, an RSA-OAEP encryption key. One key pair per process.
 * - `GET /authorize` checks the client, the redirect URI, `response_type=code`, PKCE S256, state
 *   and nonce, then shows one button per fixture user and Cancel. `POST /authorize` answers 303
 *   to the redirect URI with a one-time code, or with `error=access_denied` for Cancel.
 * - `POST /token` (client_secret_basic) checks the code, the PKCE verifier and the redirect URI
 *   and answers an ID token and a dummy access token. `noaud` gets no API audience; `idpfail`
 *   gets a 503.
 * - `GET /logout` redirects to an allowed `post_logout_redirect_uri`; it refuses `id_token_hint`,
 *   which the web must never put in a URL.
 * - `GET /users/<username>/groups`: the group directory; 404 for unknown users.
 * - `POST /test/id-token {username}`: an ID token for seeding.
 *
 * Fault proxy (`http://127.0.0.1:8197`), the web's `HURON_API_URL`: forwards to the API.
 * `POST /__test/faults {subject, mode}` makes every request whose bearer token's `sub` is
 * `subject` fail with `mode`: `unavailable` (503), `unauthorized` (401 TOKEN_INVALID), `error500`
 * (500 INTERNAL; the answer's `requestId` is the problem's `context.request_id`), `reset` (the
 * socket is destroyed) or `hang` (no answer ever comes; the client gives up). `null` clears the
 * subject's faults. With `path` (`/api/v1/catalogs/heliophysics/search`) a fault applies only to
 * requests whose path starts with it, and a subject may have one fault per path: the longest that
 * matches applies, and `mode: null` with a `path` clears that one alone. Requests of other
 * subjects pass, so tests in parallel are unaffected.
 */
import {
	createHash,
	generateKeyPairSync,
	randomBytes,
	randomUUID,
	sign,
	timingSafeEqual
} from 'node:crypto';
import { createServer, request as forwardRequest } from 'node:http';
import { pathToFileURL } from 'node:url';
import {
	API_AUDIENCE,
	CLIENT_ID,
	CLIENT_SECRET,
	USERNAMES,
	USERS,
	companySubject,
	isUsername
} from './fixture.mjs';
import { LOOPBACK, e2eStack, webOriginsFrom } from './stack.mjs';

/** @typedef {import('./fixture.mjs').Username} Username */
/** @typedef {import('node:http').IncomingMessage} IncomingMessage */
/** @typedef {import('node:http').ServerResponse} ServerResponse */
/** @typedef {import('node:http').Server} Server */
/** @typedef {'unavailable' | 'unauthorized' | 'error500' | 'reset' | 'hang'} FaultMode */

/** @type {readonly FaultMode[]} */
export const FAULT_MODES = ['unavailable', 'unauthorized', 'error500', 'reset', 'hang'];

/** The heading of the sign-in page, for tests waiting on it. */
export const SIGN_IN_HEADING = 'Company sign-in';

/** @typedef {{ status: number, code: string, title: string }} ProblemKind */

/**
 * The problem documents of the answering faults, as the API itself would write them.
 * @type {Readonly<Record<Exclude<FaultMode, 'reset' | 'hang'>, ProblemKind>>}
 */
const PROBLEMS = {
	unavailable: { status: 503, code: 'DEPENDENCY_UNAVAILABLE', title: 'Dependency unavailable' },
	unauthorized: { status: 401, code: 'TOKEN_INVALID', title: 'Token invalid' },
	error500: { status: 500, code: 'INTERNAL', title: 'Internal error' }
};

const REQUEST_TTL_MS = 10 * 60_000;
const CODE_TTL_MS = 60_000;
const ID_TOKEN_TTL_SECONDS = 300;
const MAX_BODY_BYTES = 64 * 1024;
const PKCE_CHALLENGE = /^[A-Za-z0-9_-]{43}$/;
const PKCE_VERIFIER = /^[A-Za-z0-9._~-]{43,128}$/;

/**
 * @typedef {object} FakeIdpOptions
 * @property {number} idpPort
 * @property {number} proxyPort
 * @property {string} apiUrl The API the proxy forwards to.
 * @property {readonly string[]} webOrigins Origins whose `/auth/callback` and
 *   `/login?status=signed-out` are allowed redirect targets.
 * @property {string} [host]
 */

/**
 * @typedef {object} FakeIdp
 * @property {string} issuer
 * @property {string} proxyUrl
 * @property {() => Promise<void>} close
 */

/**
 * Start the IdP and the fault proxy. The proxy listens first, so once the IdP answers both do.
 * @param {FakeIdpOptions} options
 * @returns {Promise<FakeIdp>}
 */
export async function startFakeIdp({ idpPort, proxyPort, apiUrl, webOrigins, host = LOOPBACK }) {
	const issuer = `http://${host}:${idpPort}`;
	const provider = new IdentityProvider(issuer, webOrigins);
	const proxy = new FaultProxy(new URL(apiUrl));
	const proxyServer = createServer((request, response) => proxy.handle(request, response));
	const idpServer = createServer((request, response) => {
		provider.handle(request, response).catch((failure) => answerFailure(response, failure));
	});
	await listen(proxyServer, proxyPort, host);
	try {
		await listen(idpServer, idpPort, host);
	} catch (failure) {
		await close(proxyServer);
		throw failure;
	}
	return {
		issuer,
		proxyUrl: `http://${host}:${proxyPort}`,
		close: async () => {
			await Promise.all([close(idpServer), close(proxyServer)]);
		}
	};
}

/** An answer with a status, for failures inside a handler. */
class HttpError extends Error {
	/**
	 * @param {number} status
	 * @param {string} message
	 */
	constructor(status, message) {
		super(message);
		this.name = 'HttpError';
		this.status = status;
	}
}

/**
 * @typedef {object} AuthorizationRequest
 * @property {string} redirectUri
 * @property {string} state
 * @property {string} nonce
 * @property {string} codeChallenge
 * @property {string} scope
 * @property {number} expiresAt
 */

/** @typedef {AuthorizationRequest & { username: Username }} AuthorizationCode */

/** The OIDC provider and the group directory. */
class IdentityProvider {
	/** @type {string} */
	#issuer;
	/** @type {ReadonlySet<string>} */
	#redirectUris;
	/** @type {ReadonlySet<string>} */
	#postLogoutUris;
	/** @type {import('node:crypto').KeyObject} */
	#signingKey;
	/** @type {string} */
	#kid;
	/** @type {{ keys: Record<string, string>[] }} */
	#jwks;
	/** @type {Map<string, AuthorizationRequest>} */
	#requests = new Map();
	/** @type {Map<string, AuthorizationCode>} */
	#codes = new Map();

	/**
	 * @param {string} issuer
	 * @param {readonly string[]} webOrigins
	 */
	constructor(issuer, webOrigins) {
		this.#issuer = issuer;
		this.#redirectUris = new Set(webOrigins.map((origin) => `${origin}/auth/callback`));
		this.#postLogoutUris = new Set(webOrigins.map((origin) => `${origin}/login?status=signed-out`));
		const signing = generateKeyPairSync('rsa', { modulusLength: 2048 });
		const encryption = generateKeyPairSync('rsa', { modulusLength: 2048 });
		const signingJwk = rsaJwk(signing.publicKey);
		const encryptionJwk = rsaJwk(encryption.publicKey);
		this.#signingKey = signing.privateKey;
		this.#kid = thumbprint(signingJwk);
		this.#jwks = {
			keys: [
				{ ...signingJwk, kid: this.#kid, alg: 'RS256', use: 'sig' },
				{ ...encryptionJwk, kid: thumbprint(encryptionJwk), alg: 'RSA-OAEP', use: 'enc' }
			]
		};
	}

	/**
	 * @param {IncomingMessage} request
	 * @param {ServerResponse} response
	 */
	async handle(request, response) {
		const url = new URL(request.url ?? '/', this.#issuer);
		const routes = {
			'GET /.well-known/openid-configuration': () => sendJson(response, 200, this.#discovery()),
			'GET /jwks': () => sendJson(response, 200, this.#jwks),
			'GET /authorize': () => this.#authorize(url, response),
			'POST /authorize': () => this.#decide(request, response),
			'POST /token': () => this.#token(request, response),
			'GET /logout': () => this.#logout(url, response),
			'POST /test/id-token': () => this.#testIdToken(request, response)
		};
		const route = Object.entries(routes).find(
			([key]) => key === `${request.method} ${url.pathname}`
		);
		if (route !== undefined) return route[1]();
		const directory = /^\/users\/([^/]+)\/groups$/.exec(url.pathname);
		if (directory !== null && request.method === 'GET') return this.#groups(directory[1], response);
		const known = Object.keys(routes).some((key) => key.endsWith(` ${url.pathname}`));
		sendJson(response, known ? 405 : 404, { error: known ? 'method_not_allowed' : 'not_found' });
	}

	#discovery() {
		const issuer = this.#issuer;
		return {
			issuer,
			authorization_endpoint: `${issuer}/authorize`,
			token_endpoint: `${issuer}/token`,
			jwks_uri: `${issuer}/jwks`,
			end_session_endpoint: `${issuer}/logout`,
			response_types_supported: ['code'],
			grant_types_supported: ['authorization_code'],
			subject_types_supported: ['public'],
			id_token_signing_alg_values_supported: ['RS256'],
			token_endpoint_auth_methods_supported: ['client_secret_basic'],
			code_challenge_methods_supported: ['S256'],
			scopes_supported: ['openid', 'profile', 'email']
		};
	}

	/**
	 * Validate an authorization request and show the sign-in page. Without a known client and
	 * an allowed redirect URI nothing may be redirected, so those failures are shown here.
	 * @param {URL} url
	 * @param {ServerResponse} response
	 */
	#authorize(url, response) {
		const params = url.searchParams;
		const redirectUri = params.get('redirect_uri') ?? '';
		if (params.get('client_id') !== CLIENT_ID) {
			return sendPage(response, 400, 'Unknown client', '<p>The client_id is not registered.</p>');
		}
		if (!this.#redirectUris.has(redirectUri)) {
			return sendPage(
				response,
				400,
				'Redirect URI not allowed',
				`<p><code>${escapeHtml(redirectUri)}</code> is not a registered redirect URI.</p>`
			);
		}
		const state = params.get('state') ?? '';
		const nonce = params.get('nonce') ?? '';
		const codeChallenge = params.get('code_challenge') ?? '';
		const scope = params.get('scope') ?? '';
		const problem = authorizationProblem(params);
		if (problem !== null) {
			return redirect(
				response,
				withQuery(redirectUri, {
					error: problem.error,
					error_description: problem.description,
					state
				})
			);
		}
		prune(this.#requests);
		const id = randomBytes(24).toString('base64url');
		this.#requests.set(id, {
			redirectUri,
			state,
			nonce,
			codeChallenge,
			scope,
			expiresAt: Date.now() + REQUEST_TTL_MS
		});
		sendPage(response, 200, SIGN_IN_HEADING, signInForm(id, redirectUri));
	}

	/**
	 * The sign-in page's answer: a one-time code for the chosen user, or Cancel.
	 * @param {IncomingMessage} request
	 * @param {ServerResponse} response
	 */
	async #decide(request, response) {
		const form = new URLSearchParams(await readBody(request));
		const id = form.get('request') ?? '';
		const pending = this.#requests.get(id);
		this.#requests.delete(id);
		if (pending === undefined || pending.expiresAt <= Date.now()) {
			return sendPage(
				response,
				400,
				'Sign-in request expired',
				'<p>This sign-in request expired or was already used. Start again from Huron.</p>'
			);
		}
		const { redirectUri, state } = pending;
		if (form.get('action') === 'cancel') {
			return redirect(
				response,
				withQuery(redirectUri, {
					error: 'access_denied',
					error_description: 'The user cancelled the sign-in.',
					state
				})
			);
		}
		const username = form.get('username') ?? '';
		if (!isUsername(username)) {
			return sendPage(response, 400, 'Unknown user', '<p>Choose one of the listed users.</p>');
		}
		prune(this.#codes);
		const code = randomBytes(32).toString('base64url');
		this.#codes.set(code, { ...pending, username, expiresAt: Date.now() + CODE_TTL_MS });
		redirect(response, withQuery(redirectUri, { code, state }));
	}

	/**
	 * Redeem a code: client_secret_basic, the code once, the same redirect URI, PKCE S256.
	 * @param {IncomingMessage} request
	 * @param {ServerResponse} response
	 */
	async #token(request, response) {
		const noStore = { 'cache-control': 'no-store', pragma: 'no-cache' };
		const client = basicCredentials(request.headers.authorization);
		if (client === null || client.id !== CLIENT_ID || !sameText(client.secret, CLIENT_SECRET)) {
			return sendJson(
				response,
				401,
				{ error: 'invalid_client' },
				{ ...noStore, 'www-authenticate': 'Basic realm="fake-idp"' }
			);
		}
		const form = new URLSearchParams(await readBody(request));
		/** @type {(error: string, description: string) => void} */
		const refuse = (error, description) =>
			sendJson(response, 400, { error, error_description: description }, noStore);
		if (form.get('grant_type') !== 'authorization_code') {
			return refuse('unsupported_grant_type', 'grant_type must be authorization_code');
		}
		const formClient = form.get('client_id');
		if (formClient !== null && formClient !== client.id) {
			return refuse('invalid_request', 'client_id differs from the authenticated client');
		}
		const code = form.get('code') ?? '';
		const grant = this.#codes.get(code);
		this.#codes.delete(code);
		if (grant === undefined || grant.expiresAt <= Date.now()) {
			return refuse('invalid_grant', 'the code is unknown, used or expired');
		}
		if (form.get('redirect_uri') !== grant.redirectUri) {
			return refuse('invalid_grant', 'redirect_uri differs from the authorization request');
		}
		const verifier = form.get('code_verifier') ?? '';
		if (!PKCE_VERIFIER.test(verifier) || s256(verifier) !== grant.codeChallenge) {
			return refuse('invalid_grant', 'the PKCE code_verifier does not match');
		}
		if (USERS[grant.username].special === 'token-endpoint-unavailable') {
			return sendJson(response, 503, { error: 'temporarily_unavailable' }, noStore);
		}
		sendJson(
			response,
			200,
			{
				access_token: randomBytes(32).toString('base64url'),
				token_type: 'Bearer',
				expires_in: ID_TOKEN_TTL_SECONDS,
				scope: grant.scope,
				id_token: this.#idToken(grant.username, grant.nonce)
			},
			noStore
		);
	}

	/**
	 * RP-initiated logout to an allowed `post_logout_redirect_uri`.
	 * @param {URL} url
	 * @param {ServerResponse} response
	 */
	#logout(url, response) {
		const params = url.searchParams;
		if (params.has('id_token_hint')) {
			return sendPage(
				response,
				400,
				'Logout refused',
				'<p>An ID token must never appear in a URL; this provider refuses id_token_hint.</p>'
			);
		}
		const clientId = params.get('client_id');
		if (clientId !== null && clientId !== CLIENT_ID) {
			return sendPage(response, 400, 'Unknown client', '<p>The client_id is not registered.</p>');
		}
		const target = params.get('post_logout_redirect_uri');
		if (target === null) {
			return sendPage(
				response,
				200,
				'Signed out',
				'<p>You are signed out of the test provider.</p>'
			);
		}
		if (!this.#postLogoutUris.has(target)) {
			return sendPage(
				response,
				400,
				'Logout redirect not allowed',
				`<p><code>${escapeHtml(target)}</code> is not a registered post-logout redirect URI.</p>`
			);
		}
		const state = params.get('state');
		redirect(response, state === null ? target : withQuery(target, { state }), 302);
	}

	/**
	 * @param {string} encoded
	 * @param {ServerResponse} response
	 */
	#groups(encoded, response) {
		/** @type {string} */
		let username;
		try {
			username = decodeURIComponent(encoded);
		} catch {
			username = '';
		}
		if (!isUsername(username)) return sendJson(response, 404, { error: 'unknown user' });
		sendJson(response, 200, { groups: USERS[username].groups });
	}

	/**
	 * A signed ID token for seeding, without the browser.
	 * @param {IncomingMessage} request
	 * @param {ServerResponse} response
	 */
	async #testIdToken(request, response) {
		const body = parseJsonObject(await readBody(request));
		const username = body?.username;
		if (typeof username !== 'string' || !isUsername(username)) {
			return sendJson(response, 404, { error: 'unknown user' });
		}
		sendJson(response, 200, { id_token: this.#idToken(username, null) });
	}

	/**
	 * @param {Username} username
	 * @param {string | null} nonce
	 */
	#idToken(username, nonce) {
		const user = USERS[username];
		const issuedAt = Math.floor(Date.now() / 1000);
		const audiences = user.special === 'no-api-audience' ? [CLIENT_ID] : [CLIENT_ID, API_AUDIENCE];
		/** @type {Record<string, unknown>} */
		const claims = {
			iss: this.#issuer,
			aud: audiences,
			azp: CLIENT_ID,
			sub: companySubject(username),
			preferred_username: username,
			name: user.name,
			email: user.email,
			iat: issuedAt,
			exp: issuedAt + ID_TOKEN_TTL_SECONDS
		};
		if (nonce !== null) claims.nonce = nonce;
		const header = { alg: 'RS256', typ: 'JWT', kid: this.#kid };
		const input = `${base64url(header)}.${base64url(claims)}`;
		const signature = sign('sha256', Buffer.from(input), this.#signingKey).toString('base64url');
		return `${input}.${signature}`;
	}
}

/**
 * @typedef {object} Fault
 * @property {FaultMode} mode
 * @property {string} requestId The `context.request_id` of `error500` answers.
 * @property {string} path The start of the paths it applies to; `''` for every path.
 */

/** Forwards to the API, except requests of a subject with a fault. */
class FaultProxy {
	/** @type {URL} */
	#upstream;
	/** Each subject's faults, at most one per path. @type {Map<string, Fault[]>} */
	#faults = new Map();

	/** @param {URL} upstream */
	constructor(upstream) {
		this.#upstream = upstream;
	}

	/**
	 * @param {IncomingMessage} request
	 * @param {ServerResponse} response
	 */
	handle(request, response) {
		const url = new URL(request.url ?? '/', 'http://proxy.invalid');
		if (url.pathname === '/__test/faults') {
			this.#configure(request, response).catch((failure) => answerFailure(response, failure));
			return;
		}
		const subject = bearerSubject(request.headers.authorization);
		const fault = subject === null ? undefined : this.#faultOf(subject, url.pathname);
		if (fault === undefined) this.#forward(request, response);
		else this.#inject(fault, request, response, url.pathname);
	}

	/**
	 * The fault of a subject's request to `path`: the one for the longest start of the path.
	 * @param {string} subject
	 * @param {string} path
	 * @returns {Fault | undefined}
	 */
	#faultOf(subject, path) {
		/** @type {Fault | undefined} */
		let found;
		for (const fault of this.#faults.get(subject) ?? []) {
			if (path.startsWith(fault.path) && fault.path.length >= (found?.path.length ?? 0)) {
				found = fault;
			}
		}
		return found;
	}

	/**
	 * `POST {subject, mode, path?}` sets or (with `mode: null`) clears a fault; `GET` lists them.
	 * @param {IncomingMessage} request
	 * @param {ServerResponse} response
	 */
	async #configure(request, response) {
		if (request.method === 'GET') {
			const faults = [...this.#faults].flatMap(([subject, list]) =>
				list.map((fault) => ({ subject, ...fault }))
			);
			return sendJson(response, 200, { faults });
		}
		if (request.method !== 'POST') return sendJson(response, 405, { error: 'method_not_allowed' });
		const body = parseJsonObject(await readBody(request));
		const subject = body?.subject;
		const mode = body?.mode;
		const path = body?.path ?? '';
		if (typeof subject !== 'string' || subject === '') {
			return sendJson(response, 400, { error: 'subject must be a non-empty string' });
		}
		if (typeof path !== 'string' || (path !== '' && !path.startsWith('/'))) {
			return sendJson(response, 400, { error: 'path must be a string that starts with /' });
		}
		const others = (this.#faults.get(subject) ?? []).filter((fault) => fault.path !== path);
		if (mode === null) {
			if (body?.path === undefined || others.length === 0) this.#faults.delete(subject);
			else this.#faults.set(subject, others);
			return sendJson(response, 200, { subject, mode: null, requestId: null, path });
		}
		const known = FAULT_MODES.find((candidate) => candidate === mode);
		if (known === undefined) {
			return sendJson(response, 400, {
				error: `mode must be null or one of ${FAULT_MODES.join(', ')}`
			});
		}
		const fault = { mode: known, requestId: randomUUID(), path };
		this.#faults.set(subject, [...others, fault]);
		sendJson(response, 200, { subject, ...fault });
	}

	/**
	 * @param {Fault} fault
	 * @param {IncomingMessage} request
	 * @param {ServerResponse} response
	 * @param {string} path
	 */
	#inject(fault, request, response, path) {
		if (fault.mode === 'reset') {
			request.socket.destroy();
			return;
		}
		request.resume();
		// No answer ever comes; closing the proxy ends the connection.
		if (fault.mode === 'hang') return;
		const { status, code, title } = PROBLEMS[fault.mode];
		sendJson(
			response,
			status,
			{
				type: `https://huron.dev/problems/${code.toLowerCase().replaceAll('_', '-')}`,
				title,
				status,
				detail: `fault injected by the e2e proxy (${fault.mode})`,
				code,
				context: fault.mode === 'error500' ? { request_id: fault.requestId } : {},
				instance: path
			},
			{},
			'application/problem+json'
		);
	}

	/**
	 * @param {IncomingMessage} request
	 * @param {ServerResponse} response
	 */
	#forward(request, response) {
		const upstream = forwardRequest(
			{
				hostname: this.#upstream.hostname,
				port: this.#upstream.port,
				method: request.method,
				path: request.url,
				headers: { ...withoutHopHeaders(request.headers), host: this.#upstream.host }
			},
			(answer) => {
				response.writeHead(answer.statusCode ?? 502, withoutHopHeaders(answer.headers));
				answer.pipe(response);
			}
		);
		upstream.on('error', () => {
			if (response.headersSent) {
				response.destroy();
				return;
			}
			response.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' });
			response.end('The Huron API is unreachable.');
		});
		request.pipe(upstream);
	}
}

/**
 * What is wrong with an authorization request of a known client and redirect URI, if anything.
 * @param {URLSearchParams} params
 * @returns {{ error: string, description: string } | null}
 */
function authorizationProblem(params) {
	if (params.get('response_type') !== 'code') {
		return { error: 'unsupported_response_type', description: 'response_type must be code' };
	}
	if (!(params.get('scope') ?? '').split(' ').includes('openid')) {
		return { error: 'invalid_scope', description: 'scope must include openid' };
	}
	if (!params.get('state')) return { error: 'invalid_request', description: 'state is required' };
	if (!params.get('nonce')) return { error: 'invalid_request', description: 'nonce is required' };
	const challenge = params.get('code_challenge') ?? '';
	if (params.get('code_challenge_method') !== 'S256' || !PKCE_CHALLENGE.test(challenge)) {
		return { error: 'invalid_request', description: 'a PKCE S256 code_challenge is required' };
	}
	return null;
}

/**
 * The sign-in page's form: one button per fixture user, then Cancel.
 * @param {string} requestId
 * @param {string} redirectUri
 */
function signInForm(requestId, redirectUri) {
	const users = USERNAMES.map((username) => {
		const user = USERS[username];
		const name = escapeHtml(username);
		const groups = escapeHtml(user.groups.length > 0 ? user.groups.join(', ') : 'no groups');
		return `<li>
			<button type="submit" name="username" value="${name}" aria-describedby="about-${name}">
				${name}
			</button>
			<span id="about-${name}">
				<strong>${escapeHtml(user.name)}</strong> · ${groups}
				<br><small>${escapeHtml(user.about)}</small>
			</span>
		</li>`;
	}).join('\n');
	return `<p>Test identity provider for Huron's e2e tests and demo. Choose who to sign in as;
		you return to <code>${escapeHtml(redirectUri)}</code>.</p>
		<form method="post" action="/authorize">
			<input type="hidden" name="request" value="${escapeHtml(requestId)}">
			<ul>${users}</ul>
			<button type="submit" name="action" value="cancel" class="cancel">Cancel</button>
		</form>`;
}

/** The pages' own styles: light and dark, readable from 390 px up. */
const PAGE_STYLE = `
	:root {
		color-scheme: light dark;
		--bg: #f4f5f7; --card: #fff; --fg: #1d2129; --muted: #5f6773; --line: #d9dde3;
		--accent: #3554d1;
	}
	@media (prefers-color-scheme: dark) {
		:root {
			--bg: #14161a; --card: #1d2026; --fg: #e8eaee; --muted: #a3a9b4; --line: #343941;
			--accent: #8ea4ff;
		}
	}
	* { box-sizing: border-box; }
	body {
		margin: 0; min-height: 100dvh; display: grid; place-items: center; padding: 2.5rem 1rem;
		background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif;
	}
	main {
		width: 100%; max-width: 34rem; padding: 1.75rem;
		background: var(--card); border: 1px solid var(--line); border-radius: 12px;
	}
	.badge {
		display: inline-block; margin: 0 0 0.75rem; padding: 0.15rem 0.6rem;
		border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 0.8rem;
	}
	h1 { margin: 0 0 0.5rem; font-size: 1.5rem; }
	p { color: var(--muted); }
	code { overflow-wrap: anywhere; }
	ul { list-style: none; margin: 1.25rem 0; padding: 0; display: grid; gap: 0.6rem; }
	li { display: grid; grid-template-columns: 7.5rem 1fr; gap: 0.75rem; align-items: center; }
	li span { color: var(--muted); font-size: 0.85rem; overflow-wrap: anywhere; }
	li strong { color: var(--fg); }
	button {
		font: inherit; font-weight: 600; min-height: 2.5rem; padding: 0.4rem 0.9rem;
		border-radius: 8px; border: 1px solid var(--accent); background: var(--accent);
		color: var(--card); cursor: pointer;
	}
	button.cancel { background: transparent; color: var(--fg); border-color: var(--line); }
	button:focus-visible { outline: 2px solid var(--fg); outline-offset: 2px; }
	@media (max-width: 30rem) {
		body { padding: 1rem 0.75rem; }
		main { padding: 1.25rem; }
		li { grid-template-columns: 5.5rem 1fr; }
	}
`;

/**
 * @param {ServerResponse} response
 * @param {number} status
 * @param {string} title
 * @param {string} body Trusted HTML; callers escape what they interpolate.
 */
function sendPage(response, status, title, body) {
	const html = `<!doctype html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<meta name="color-scheme" content="light dark">
	<title>${escapeHtml(title)} · Test company IdP</title>
	<style>${PAGE_STYLE}</style>
</head>
<body>
	<main>
		<p class="badge">Test identity provider</p>
		<h1>${escapeHtml(title)}</h1>
		${body}
	</main>
</body>
</html>`;
	response.writeHead(status, {
		'content-type': 'text/html; charset=utf-8',
		'cache-control': 'no-store'
	});
	response.end(html);
}

/**
 * @param {ServerResponse} response
 * @param {number} status
 * @param {unknown} body
 * @param {Record<string, string>} [headers]
 * @param {string} [contentType]
 */
function sendJson(response, status, body, headers = {}, contentType = 'application/json') {
	response.writeHead(status, { 'content-type': contentType, ...headers });
	response.end(JSON.stringify(body));
}

/**
 * @param {ServerResponse} response
 * @param {string} location
 * @param {number} [status] 303 by default: after the sign-in POST the browser must follow with
 *   a GET, or `SameSite=Lax` cookies would not reach the callback.
 */
function redirect(response, location, status = 303) {
	response.writeHead(status, { location, 'cache-control': 'no-store' });
	response.end();
}

/**
 * @param {ServerResponse} response
 * @param {unknown} failure
 */
function answerFailure(response, failure) {
	if (response.headersSent) {
		response.destroy();
		return;
	}
	const status = failure instanceof HttpError ? failure.status : 500;
	const message = failure instanceof Error ? failure.message : 'unexpected failure';
	sendJson(response, status, { error: message });
}

/**
 * @param {IncomingMessage} request
 * @returns {Promise<string>}
 */
async function readBody(request) {
	/** @type {Buffer[]} */
	const chunks = [];
	let size = 0;
	for await (const chunk of request) {
		const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
		size += buffer.length;
		if (size > MAX_BODY_BYTES) throw new HttpError(413, 'request body too large');
		chunks.push(buffer);
	}
	return Buffer.concat(chunks).toString('utf8');
}

/**
 * @param {string} text
 * @returns {Record<string, unknown> | null}
 */
function parseJsonObject(text) {
	/** @type {unknown} */
	let value;
	try {
		value = JSON.parse(text);
	} catch {
		return null;
	}
	if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
	return Object.fromEntries(Object.entries(value));
}

/**
 * The `sub` of a bearer JWT, read without verification: only the proxy's fault routing uses it.
 * @param {string | undefined} header
 * @returns {string | null}
 */
function bearerSubject(header) {
	const match = /^Bearer [A-Za-z0-9_-]+\.([A-Za-z0-9_-]+)\.[A-Za-z0-9_-]*$/.exec(header ?? '');
	if (match === null) return null;
	const claims = parseJsonObject(Buffer.from(match[1], 'base64url').toString('utf8'));
	return typeof claims?.sub === 'string' ? claims.sub : null;
}

/**
 * Client credentials of `client_secret_basic`, form-decoded as RFC 6749 section 2.3.1 requires.
 * @param {string | undefined} header
 * @returns {{ id: string, secret: string } | null}
 */
function basicCredentials(header) {
	const match = /^Basic ([A-Za-z0-9+/]+={0,2})$/.exec(header ?? '');
	if (match === null) return null;
	const decoded = Buffer.from(match[1], 'base64').toString('utf8');
	const colon = decoded.indexOf(':');
	if (colon < 0) return null;
	try {
		const formDecode = (/** @type {string} */ value) =>
			decodeURIComponent(value.replaceAll('+', ' '));
		return {
			id: formDecode(decoded.slice(0, colon)),
			secret: formDecode(decoded.slice(colon + 1))
		};
	} catch {
		return null;
	}
}

/**
 * @param {string} a
 * @param {string} b
 */
function sameText(a, b) {
	const left = Buffer.from(a);
	const right = Buffer.from(b);
	return left.length === right.length && timingSafeEqual(left, right);
}

/** @param {string} verifier */
function s256(verifier) {
	return createHash('sha256').update(verifier, 'ascii').digest('base64url');
}

/** @param {unknown} value */
function base64url(value) {
	return Buffer.from(JSON.stringify(value)).toString('base64url');
}

/**
 * The public RSA key as a JWK with exactly `kty`, `n` and `e`.
 * @param {import('node:crypto').KeyObject} key
 * @returns {{ kty: string, n: string, e: string }}
 */
function rsaJwk(key) {
	const { kty, n, e } = key.export({ format: 'jwk' });
	if (kty === undefined || n === undefined || e === undefined) {
		throw new Error('the RSA key did not export as a JWK');
	}
	return { kty, n, e };
}

/**
 * RFC 7638 thumbprint: a fresh key gets a fresh `kid`, so the API never reuses a cached key.
 * @param {{ kty: string, n: string, e: string }} jwk
 */
function thumbprint({ kty, n, e }) {
	return createHash('sha256').update(JSON.stringify({ e, kty, n })).digest('base64url');
}

/**
 * @param {string} base
 * @param {Record<string, string>} params
 */
function withQuery(base, params) {
	const url = new URL(base);
	for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);
	return url.href;
}

/**
 * @template {{ expiresAt: number }} T
 * @param {Map<string, T>} entries
 */
function prune(entries) {
	const now = Date.now();
	for (const [key, entry] of entries) if (entry.expiresAt <= now) entries.delete(key);
}

/**
 * Hop-by-hop headers belong to one connection and are never forwarded.
 * @param {import('node:http').IncomingHttpHeaders} headers
 */
function withoutHopHeaders(headers) {
	const hop = new Set(['connection', 'keep-alive', 'proxy-connection', 'upgrade', 'te', 'trailer']);
	return Object.fromEntries(Object.entries(headers).filter(([name]) => !hop.has(name)));
}

/** @param {string} value */
function escapeHtml(value) {
	return value
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#39;');
}

/**
 * @param {Server} server
 * @param {number} port
 * @param {string} host
 * @returns {Promise<void>}
 */
function listen(server, port, host) {
	return new Promise((resolve, reject) => {
		server.once('error', reject);
		server.listen(port, host, () => {
			server.off('error', reject);
			resolve();
		});
	});
}

/**
 * @param {Server} server
 * @returns {Promise<void>}
 */
function close(server) {
	return new Promise((resolve) => {
		server.close(() => resolve());
		server.closeAllConnections();
	});
}

const invokedDirectly =
	process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
	const stack = e2eStack(process.env);
	const idp = await startFakeIdp({
		idpPort: stack.ports.idp,
		proxyPort: stack.ports.proxy,
		apiUrl: stack.apiUrl,
		webOrigins: webOriginsFrom(process.env, stack.webOrigins)
	});
	console.log(`fake IdP at ${idp.issuer}; fault proxy at ${idp.proxyUrl} for ${stack.apiUrl}`);
	for (const signal of /** @type {const} */ (['SIGINT', 'SIGTERM'])) {
		process.once(signal, () => {
			idp.close().then(() => process.exit(0));
		});
	}
}
