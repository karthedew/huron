/**
 * Where each process of the e2e and demo stacks listens and the environment it runs with. Every
 * setting is explicit, so nothing leaks in from `web/.env` or the developer's shell.
 *
 * Ports come from the environment and default to the harness's own:
 *
 * | Variable               | Default | Process                                              |
 * | ---------------------- | ------- | ---------------------------------------------------- |
 * | `HURON_E2E_IDP_PORT`   | 8199    | fake company IdP and group directory (the issuer)    |
 * | `HURON_E2E_PROXY_PORT` | 8197    | fault proxy in front of the API (the web's API URL)  |
 * | `HURON_E2E_API_PORT`   | 8198    | Huron API on the memory store                        |
 * | `HURON_E2E_WEB_PORT`   | 4173    | web server under test (`node build/index.js`)        |
 * | `HURON_DEMO_WEB_PORT`  | 5173    | `vite dev` of `npm run demo`                         |
 */
import {
	API_AUDIENCE,
	CLIENT_ID,
	CLIENT_SECRET,
	INSTANCE_ID,
	MOUNT_PREFIX,
	PLATFORM_ADMIN_GROUP
} from './fixture.mjs';

/** Everything but the browser-facing web origin listens on IPv4 loopback. */
export const LOOPBACK = '127.0.0.1';

/** The Playwright project of `e2e/faults/`, whose tests inject API faults one at a time. */
export const FAULTS_PROJECT = 'faults';

/**
 * @typedef {object} Ports
 * @property {number} idp
 * @property {number} proxy
 * @property {number} api
 * @property {number} web
 */

/**
 * @typedef {object} Stack
 * @property {Ports} ports
 * @property {string} issuer The fake IdP's issuer; also its group directory and test endpoints.
 * @property {string} proxyUrl The fault proxy; the web's `HURON_API_URL`.
 * @property {string} apiUrl The API itself, for seeding.
 * @property {string} webOrigin The origin browsers use.
 * @property {readonly string[]} webOrigins Every origin the IdP may redirect back to.
 */

/** @typedef {Record<string, string | undefined>} Environment */

/**
 * The e2e stack. The browser reaches the web as `localhost` while the IdP and the API are
 * `127.0.0.1`, so they are cross-site and the cookies' `SameSite` rules matter.
 * @param {Environment} env
 * @returns {Stack}
 */
export function e2eStack(env) {
	const ports = backendPorts(env, port(env, 'HURON_E2E_WEB_PORT', 4173));
	const webOrigin = `http://localhost:${ports.web}`;
	return stack(ports, webOrigin, [webOrigin]);
}

/**
 * The demo stack: `vite dev` may be opened as `localhost` or `127.0.0.1`.
 * @param {Environment} env
 * @returns {Stack}
 */
export function demoStack(env) {
	const ports = backendPorts(env, port(env, 'HURON_DEMO_WEB_PORT', 5173));
	return stack(ports, `http://localhost:${ports.web}`, [
		`http://localhost:${ports.web}`,
		`http://${LOOPBACK}:${ports.web}`
	]);
}

/**
 * The fake IdP's environment; `fake-idp.mjs` reads it when run as a program.
 * @param {Stack} stack
 * @returns {Record<string, string>}
 */
export function idpEnvironment(stack) {
	return {
		HURON_E2E_IDP_PORT: String(stack.ports.idp),
		HURON_E2E_PROXY_PORT: String(stack.ports.proxy),
		HURON_E2E_API_PORT: String(stack.ports.api),
		HURON_E2E_WEB_ORIGINS: stack.webOrigins.join(',')
	};
}

/**
 * The origins the fake IdP redirects back to, from `HURON_E2E_WEB_ORIGINS` (comma-separated).
 * @param {Environment} env
 * @param {readonly string[]} fallback
 * @returns {string[]}
 */
export function webOriginsFrom(env, fallback) {
	const listed = (env.HURON_E2E_WEB_ORIGINS ?? '')
		.split(',')
		.map((origin) => origin.trim())
		.filter(Boolean);
	for (const origin of listed) {
		if (new URL(origin).origin !== origin) {
			throw new Error(`HURON_E2E_WEB_ORIGINS: ${origin} is not an origin`);
		}
	}
	return listed.length > 0 ? listed : [...fallback];
}

/**
 * Every setting of the API, on the memory store, trusting the fake IdP.
 * @param {Stack} stack
 * @returns {Record<string, string>}
 */
export function apiEnvironment(stack) {
	return {
		HURON_STORE: 'memory',
		HURON_DATABASE_URL: '',
		HURON_INSTANCE_ID: INSTANCE_ID,
		HURON_ISSUER: stack.apiUrl,
		HURON_AUDIENCE: 'huron',
		HURON_TOKEN_TTL_SECONDS: '28800',
		HURON_KEY_OVERLAP_HOURS: '24',
		HURON_KEY_CACHE_SECONDS: '60',
		HURON_COMPANY_ISSUER: stack.issuer,
		HURON_COMPANY_AUDIENCE: API_AUDIENCE,
		HURON_GROUP_DIRECTORY_URL: stack.issuer,
		HURON_PLATFORM_ADMIN_GROUP: PLATFORM_ADMIN_GROUP,
		HURON_POOL_SIZE: '10',
		HURON_LOG_LEVEL: 'INFO'
	};
}

/**
 * The API's command line, run from the repository root. `--no-sync` and `--offline`: the run
 * uses the project's environment as it is and never downloads or installs anything.
 * @param {Stack} stack
 * @returns {string[]}
 */
export function apiCommand(stack) {
	return [
		'uv',
		'run',
		'--offline',
		'--no-sync',
		'uvicorn',
		'huron.applications.api.main:app',
		'--host',
		LOOPBACK,
		'--port',
		String(stack.ports.api),
		'--log-level',
		'warning',
		'--no-access-log'
	];
}

/**
 * Every setting of the web server: the API behind the fault proxy and the fake IdP's
 * confidential client. `vite dev` ignores `ORIGIN`, `HOST` and `PORT`.
 * @param {Stack} stack
 * @returns {Record<string, string>}
 */
export function webEnvironment(stack) {
	return {
		ORIGIN: stack.webOrigin,
		HOST: LOOPBACK,
		PORT: String(stack.ports.web),
		HURON_API_URL: stack.proxyUrl,
		HURON_WEB_OIDC_ISSUER: stack.issuer,
		HURON_WEB_OIDC_CLIENT_ID: CLIENT_ID,
		HURON_WEB_OIDC_CLIENT_SECRET: CLIENT_SECRET,
		HURON_WEB_OIDC_SCOPES: 'openid profile email',
		HURON_WEB_OIDC_LOGOUT: 'true',
		HURON_WEB_MOUNT_PREFIX: MOUNT_PREFIX,
		HURON_WEB_API_TIMEOUT_MS: '10000'
	};
}

/**
 * @param {Environment} env
 * @param {number} web
 * @returns {Ports}
 */
function backendPorts(env, web) {
	return {
		idp: port(env, 'HURON_E2E_IDP_PORT', 8199),
		proxy: port(env, 'HURON_E2E_PROXY_PORT', 8197),
		api: port(env, 'HURON_E2E_API_PORT', 8198),
		web
	};
}

/**
 * @param {Ports} ports
 * @param {string} webOrigin
 * @param {readonly string[]} webOrigins
 * @returns {Stack}
 */
function stack(ports, webOrigin, webOrigins) {
	return {
		ports,
		issuer: `http://${LOOPBACK}:${ports.idp}`,
		proxyUrl: `http://${LOOPBACK}:${ports.proxy}`,
		apiUrl: `http://${LOOPBACK}:${ports.api}`,
		webOrigin,
		webOrigins
	};
}

/**
 * @param {Environment} env
 * @param {string} name
 * @param {number} fallback
 * @returns {number}
 */
function port(env, name, fallback) {
	const value = env[name];
	if (value === undefined || value === '') return fallback;
	const parsed = /^\d{1,5}$/.test(value) ? Number(value) : Number.NaN;
	if (!(parsed >= 1 && parsed <= 65_535))
		throw new Error(`${name} must be a TCP port, not ${value}`);
	return parsed;
}
