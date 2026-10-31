// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfigError, getConfig, parseConfig, publicOrigin, resetConfig } from './config';

const environment = vi.hoisted((): Record<string, string> => ({}));
vi.mock('$env/dynamic/private', () => ({ env: environment }));
vi.mock('$app/environment', () => ({
	dev: false,
	browser: false,
	building: false,
	version: 'test'
}));

const VALID = {
	ORIGIN: 'https://huron-web.apps.example.org',
	HURON_API_URL: 'http://127.0.0.1:8080',
	HURON_WEB_OIDC_ISSUER: 'http://127.0.0.1:8081/realms/company',
	HURON_WEB_OIDC_CLIENT_ID: 'huron-web'
};

function parse(overrides: Record<string, string | undefined> = {}, dev = false) {
	return parseConfig({ ...VALID, ...overrides }, { dev });
}

function failure(overrides: Record<string, string | undefined>, dev = false): ConfigError {
	try {
		parse(overrides, dev);
	} catch (error) {
		if (error instanceof ConfigError) return error;
		throw error;
	}
	throw new Error('expected a ConfigError');
}

describe('parseConfig', () => {
	it('reads the required settings and applies the defaults', () => {
		expect(parse()).toEqual({
			origin: 'https://huron-web.apps.example.org',
			apiUrl: 'http://127.0.0.1:8080',
			oidc: {
				issuer: 'http://127.0.0.1:8081/realms/company',
				clientId: 'huron-web',
				clientSecret: null,
				scopes: 'openid profile email',
				logout: true
			},
			mountPrefix: '/projects/huron',
			apiTimeoutMs: 10_000,
			exchangeTimeoutMs: 35_000
		});
	});

	it('reads every optional setting', () => {
		const config = parse({
			HURON_WEB_OIDC_CLIENT_SECRET: 's3cret',
			HURON_WEB_OIDC_SCOPES: '  openid   email ',
			HURON_WEB_OIDC_LOGOUT: 'false',
			HURON_WEB_MOUNT_PREFIX: '/mnt/share/',
			HURON_WEB_API_TIMEOUT_MS: '20000'
		});
		expect(config.oidc).toMatchObject({
			clientSecret: 's3cret',
			scopes: 'openid email',
			logout: false
		});
		expect(config.mountPrefix).toBe('/mnt/share');
		expect(config.apiTimeoutMs).toBe(20_000);
		expect(config.exchangeTimeoutMs).toBe(60_000);
	});

	it('normalizes origins and strips trailing slashes from the issuer', () => {
		const config = parse({
			ORIGIN: 'https://huron-web.apps.example.org/',
			HURON_API_URL: 'http://api.internal:8080/',
			HURON_WEB_OIDC_ISSUER: 'https://idp.example.org/realms/company//'
		});
		expect(config.origin).toBe('https://huron-web.apps.example.org');
		expect(config.apiUrl).toBe('http://api.internal:8080');
		expect(config.oidc.issuer).toBe('https://idp.example.org/realms/company');
	});

	it('treats empty strings as unset', () => {
		expect(
			parse({ HURON_WEB_OIDC_CLIENT_SECRET: '', HURON_WEB_OIDC_SCOPES: '' }).oidc
		).toMatchObject({ clientSecret: null, scopes: 'openid profile email' });
		expect(failure({ HURON_API_URL: '' }).variable).toBe('HURON_API_URL');
	});

	it('does not need ORIGIN in dev, where each request supplies its origin', () => {
		expect(parse({ ORIGIN: undefined }, true).origin).toBeNull();
		expect(parse({ ORIGIN: 'not a url' }, true).origin).toBeNull();
	});

	it.each([
		['ORIGIN', { ORIGIN: undefined }, 'is required'],
		['HURON_API_URL', { HURON_API_URL: undefined }, 'is required'],
		['HURON_WEB_OIDC_ISSUER', { HURON_WEB_OIDC_ISSUER: undefined }, 'is required'],
		['HURON_WEB_OIDC_CLIENT_ID', { HURON_WEB_OIDC_CLIENT_ID: undefined }, 'is required']
	])('requires %s', (variable, overrides, problem) => {
		expect(failure(overrides).message).toBe(`${variable} ${problem}`);
	});

	it.each([
		['ORIGIN', 'huron.example.org', 'must be an absolute http(s) URL'],
		['ORIGIN', 'ftp://huron.example.org', 'must be an absolute http(s) URL'],
		['ORIGIN', 'https://huron.example.org/app', 'must be an origin without a path'],
		['ORIGIN', 'https://huron.example.org/?x=1', 'must not have a query or fragment'],
		['ORIGIN', 'https://user:pw@huron.example.org', 'must not contain credentials'],
		['HURON_API_URL', 'http://127.0.0.1:8080/api/v1', 'must be an origin without a path'],
		['HURON_API_URL', 'http://127.0.0.1:8080#top', 'must not have a query or fragment'],
		['HURON_WEB_OIDC_ISSUER', 'http://idp/realms/company?x=1', 'must not have a query or fragment'],
		['HURON_WEB_OIDC_ISSUER', ' http://idp/realms/company', 'must not contain whitespace'],
		['HURON_WEB_OIDC_CLIENT_ID', 'huron web', 'must not contain whitespace or control characters'],
		['HURON_WEB_OIDC_SCOPES', 'profile email', 'must include openid'],
		['HURON_WEB_OIDC_LOGOUT', 'yes', 'must be true or false'],
		['HURON_WEB_MOUNT_PREFIX', 'projects/huron', 'must be an absolute path'],
		...['0', '1.5', '600001', 'soon'].map((value) => [
			'HURON_WEB_API_TIMEOUT_MS',
			value,
			'must be a whole number of milliseconds from 1 to 600000'
		])
	])('rejects %s=%j with a message that names only the variable', (variable, value, problem) => {
		const error = failure({ [variable]: value });
		expect(error.variable).toBe(variable);
		expect(error.message).toBe(`${variable} ${problem}`);
	});

	it('keeps the client secret out of every error message', () => {
		const error = failure({ HURON_WEB_OIDC_CLIENT_SECRET: 'very-secret', HURON_API_URL: 'x' });
		expect(error.message).not.toContain('very-secret');
	});

	it('gives the exchange at least 35 s and otherwise three API timeouts', () => {
		expect(parse({ HURON_WEB_API_TIMEOUT_MS: '1000' }).exchangeTimeoutMs).toBe(35_000);
		expect(parse({ HURON_WEB_API_TIMEOUT_MS: '15000' }).exchangeTimeoutMs).toBe(45_000);
	});
});

describe('getConfig', () => {
	beforeEach(() => {
		for (const key of Object.keys(environment)) delete environment[key];
		resetConfig();
	});

	it('reads the environment once and memoizes the result', () => {
		Object.assign(environment, VALID);
		const first = getConfig();
		environment.HURON_API_URL = 'http://other:9000';
		expect(getConfig()).toBe(first);
		resetConfig();
		expect(getConfig().apiUrl).toBe('http://other:9000');
	});

	it('throws a ConfigError at first use, not at import', () => {
		expect(() => getConfig()).toThrow(ConfigError);
	});
});

describe('publicOrigin', () => {
	it('prefers ORIGIN and falls back to the request origin in dev', () => {
		const url = new URL('http://localhost:5173/catalogs');
		expect(publicOrigin(parse(), url)).toBe('https://huron-web.apps.example.org');
		expect(publicOrigin(parse({}, true), url)).toBe('http://localhost:5173');
	});
});
