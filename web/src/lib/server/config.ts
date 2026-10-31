import { dev } from '$app/environment';
import { env } from '$env/dynamic/private';

/** A missing or invalid setting. The message names the variable, never its value. */
export class ConfigError extends Error {
	readonly variable: string;

	constructor(variable: string, problem: string) {
		super(`${variable} ${problem}`);
		this.name = 'ConfigError';
		this.variable = variable;
	}
}

export interface OidcSettings {
	/** The company IdP issuer without a trailing slash. */
	issuer: string;
	clientId: string;
	/** `null` for a public client. */
	clientSecret: string | null;
	scopes: string;
	/** Whether logout continues to the IdP's `end_session_endpoint`. */
	logout: boolean;
}

export interface Config {
	/** The public origin, e.g. `https://huron.example.org`; `null` in `vite dev`. */
	origin: string | null;
	/** The API origin; the client appends `/api/v1`. */
	apiUrl: string;
	oidc: OidcSettings;
	/** Where the share is mounted; share paths are shown as `<prefix>/<relative path>`. */
	mountPrefix: string;
	apiTimeoutMs: number;
	exchangeTimeoutMs: number;
}

const DEFAULT_SCOPES = 'openid profile email';
const DEFAULT_MOUNT_PREFIX = '/projects/huron';
const DEFAULT_TIMEOUT_MS = 10_000;
const MAX_TIMEOUT_MS = 600_000;
/** The API's own dependency errors must arrive before the web gives up on an exchange. */
const MIN_EXCHANGE_TIMEOUT_MS = 35_000;

/** Parse the web's settings; an empty string counts as unset. */
export function parseConfig(
	source: Record<string, string | undefined>,
	options: { dev: boolean }
): Config {
	const read = (name: string): string | undefined => {
		const value = source[name];
		return value === undefined || value === '' ? undefined : value;
	};
	const required = (name: string): string => {
		const value = read(name);
		if (value === undefined) throw new ConfigError(name, 'is required');
		return value;
	};

	const origin = options.dev ? null : httpOrigin('ORIGIN', required('ORIGIN'));
	const apiTimeoutMs = timeout('HURON_WEB_API_TIMEOUT_MS', read('HURON_WEB_API_TIMEOUT_MS'));
	const clientSecret = read('HURON_WEB_OIDC_CLIENT_SECRET') ?? null;
	return {
		origin,
		apiUrl: httpOrigin('HURON_API_URL', required('HURON_API_URL')),
		oidc: {
			issuer: issuer('HURON_WEB_OIDC_ISSUER', required('HURON_WEB_OIDC_ISSUER')),
			clientId: plainText('HURON_WEB_OIDC_CLIENT_ID', required('HURON_WEB_OIDC_CLIENT_ID')),
			clientSecret,
			scopes: scopes('HURON_WEB_OIDC_SCOPES', read('HURON_WEB_OIDC_SCOPES') ?? DEFAULT_SCOPES),
			logout: flag('HURON_WEB_OIDC_LOGOUT', read('HURON_WEB_OIDC_LOGOUT') ?? 'true')
		},
		mountPrefix: mountPrefix(
			'HURON_WEB_MOUNT_PREFIX',
			read('HURON_WEB_MOUNT_PREFIX') ?? DEFAULT_MOUNT_PREFIX
		),
		apiTimeoutMs,
		exchangeTimeoutMs: Math.max(MIN_EXCHANGE_TIMEOUT_MS, 3 * apiTimeoutMs)
	};
}

let memo: Config | undefined;

/** The settings of this process, read from `$env/dynamic/private` at first use. */
export function getConfig(): Config {
	memo ??= parseConfig(env, { dev });
	return memo;
}

/** Forget the memoized settings so the next `getConfig()` reads the environment again. */
export function resetConfig(): void {
	memo = undefined;
}

/** The origin browsers use: `ORIGIN`, or the request's own origin in `vite dev`. */
export function publicOrigin(config: Config, url: URL): string {
	return config.origin ?? url.origin;
}

function httpUrl(name: string, value: string): URL {
	if (/\s/.test(value)) throw new ConfigError(name, 'must not contain whitespace');
	let url: URL;
	try {
		url = new URL(value);
	} catch {
		throw new ConfigError(name, 'must be an absolute http(s) URL');
	}
	if (url.protocol !== 'http:' && url.protocol !== 'https:') {
		throw new ConfigError(name, 'must be an absolute http(s) URL');
	}
	if (url.username || url.password) throw new ConfigError(name, 'must not contain credentials');
	if (url.search || url.hash || value.includes('?') || value.includes('#')) {
		throw new ConfigError(name, 'must not have a query or fragment');
	}
	return url;
}

function httpOrigin(name: string, value: string): string {
	const url = httpUrl(name, value);
	if (url.pathname !== '/') throw new ConfigError(name, 'must be an origin without a path');
	return url.origin;
}

function issuer(name: string, value: string): string {
	httpUrl(name, value);
	return value.replace(/\/+$/, '');
}

function plainText(name: string, value: string): string {
	if (/[\s\p{Cc}]/u.test(value)) {
		throw new ConfigError(name, 'must not contain whitespace or control characters');
	}
	return value;
}

function scopes(name: string, value: string): string {
	const list = value.split(/\s+/).filter(Boolean);
	if (!list.includes('openid')) throw new ConfigError(name, 'must include openid');
	return list.join(' ');
}

function flag(name: string, value: string): boolean {
	if (value === 'true') return true;
	if (value === 'false') return false;
	throw new ConfigError(name, 'must be true or false');
}

function mountPrefix(name: string, value: string): string {
	if (!value.startsWith('/') || /[\p{Cc}\\]/u.test(value)) {
		throw new ConfigError(name, 'must be an absolute path');
	}
	return value.replace(/\/+$/, '');
}

function timeout(name: string, value: string | undefined): number {
	if (value === undefined) return DEFAULT_TIMEOUT_MS;
	const parsed = /^\d+$/.test(value) ? Number(value) : Number.NaN;
	if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > MAX_TIMEOUT_MS) {
		throw new ConfigError(
			name,
			`must be a whole number of milliseconds from 1 to ${MAX_TIMEOUT_MS}`
		);
	}
	return parsed;
}
