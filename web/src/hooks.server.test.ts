// @vitest-environment node
import { isHttpError, isRedirect, type RequestEvent } from '@sveltejs/kit';
import * as devalue from 'devalue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetConfig } from '$lib/server/config';
import { sessionStore } from '$lib/server/sessions';
import { fakeRequestEvent } from '$lib/testing/events';
import { FakeCookies } from '$lib/testing/fake-cookies';
import { handle, handleError } from './hooks.server';

const environment = vi.hoisted((): Record<string, string> => ({}));
vi.mock('$env/dynamic/private', () => ({ env: environment }));
vi.mock('$app/environment', () => ({
	dev: false,
	browser: false,
	building: false,
	version: 'test'
}));

const SETTINGS = {
	ORIGIN: 'http://localhost:4173',
	HURON_API_URL: 'http://127.0.0.1:8197',
	HURON_WEB_OIDC_ISSUER: 'http://127.0.0.1:8199',
	HURON_WEB_OIDC_CLIENT_ID: 'huron-web'
};

beforeEach(() => {
	for (const key of Object.keys(environment)) delete environment[key];
	Object.assign(environment, SETTINGS);
	resetConfig();
});

afterEach(() => {
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
	vi.restoreAllMocks();
});

function session(token = 'huron-token-value') {
	return sessionStore().create({
		huronToken: token,
		tokenExpiresAt: new Date(Date.now() + 3_600_000).toISOString(),
		subject: 'sub-erin',
		name: 'Erin Example',
		groups: ['helio-readers']
	}).id;
}

function request(
	path: string,
	init: { cookies?: FakeCookies; headers?: Record<string, string> } = {}
) {
	return fakeRequestEvent({
		url: `${environment.ORIGIN}${path}`,
		routeId: null,
		params: {},
		cookies: init.cookies,
		request: { headers: init.headers }
	});
}

async function run(event: RequestEvent, answer: () => Response = () => new Response('page')) {
	const resolve = vi.fn(async () => answer());
	try {
		return { response: await handle({ event, resolve }), resolve, thrown: undefined };
	} catch (thrown) {
		return { response: undefined, resolve, thrown };
	}
}

describe('handle', () => {
	it.each(['/login', '/auth/login', '/auth/callback', '/logout', '/healthz'])(
		'lets %s through without a session',
		async (path) => {
			const event = request(path);
			const { response, resolve } = await run(event);
			expect(resolve).toHaveBeenCalledOnce();
			expect(event.locals.user).toBeNull();
			expect(response?.status).toBe(200);
		}
	);

	it('sends any other request without a session to the login page', async () => {
		const { thrown, resolve } = await run(request('/'));
		expect(isRedirect(thrown) && [thrown.status, thrown.location]).toEqual([
			303,
			'/login?returnTo=%2F'
		]);
		expect(resolve).not.toHaveBeenCalled();
	});

	it('keeps the requested page and query as returnTo', async () => {
		const { thrown } = await run(request('/catalogs/heliophysics/search?q=solar%20wind'));
		expect(isRedirect(thrown) && thrown.location).toBe(
			'/login?returnTo=%2Fcatalogs%2Fheliophysics%2Fsearch%3Fq%3Dsolar%2520wind'
		);
	});

	it('treats a cookie whose session is gone as expired and deletes it', async () => {
		const cookies = new FakeCookies({ huron_session: 'gone' });
		const { thrown } = await run(request('/orgs', { cookies }));
		expect(isRedirect(thrown) && thrown.location).toBe('/login?returnTo=%2Forgs&status=expired');
		expect(cookies.lastWrite('huron_session')?.value).toBeNull();
	});

	it('answers programmatic requests without a session with JSON', async () => {
		const { response } = await run(
			request('/catalogs/heliophysics/tree?parent=a', { headers: { 'x-huron-fetch': '1' } })
		);
		expect(response?.status).toBe(401);
		expect(await response?.json()).toEqual({ code: 'UNAUTHENTICATED' });
		expect(response?.headers.get('x-content-type-options')).toBe('nosniff');
		expect(response?.headers.get('cache-control')).toBe('private, no-store');
		expect(response?.headers.has('set-cookie')).toBe(false);
	});

	it('deletes a cookie whose session is gone on the JSON answer as well', async () => {
		const cookies = new FakeCookies({ huron_session: 'gone' });
		const { response, resolve } = await run(
			request('/catalogs/heliophysics/tree?parent=a', {
				cookies,
				headers: { 'x-huron-fetch': '1' }
			})
		);
		expect(resolve).not.toHaveBeenCalled();
		expect(response?.status).toBe(401);
		expect(await response?.json()).toEqual({ code: 'UNAUTHENTICATED' });
		expect(response?.headers.get('set-cookie')).toBe(
			'huron_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax'
		);
	});

	it('puts only plain user data into locals', async () => {
		const id = session('secret-huron-token');
		const event = request('/', { cookies: new FakeCookies({ huron_session: id }) });
		await run(event);
		expect(event.locals.user).toMatchObject({
			subject: 'sub-erin',
			name: 'Erin Example',
			groups: ['helio-readers']
		});
		for (const serialized of [devalue.stringify(event.locals), devalue.uneval(event.locals)]) {
			expect(serialized).toContain('Erin Example');
			expect(serialized).not.toContain('secret-huron-token');
			expect(serialized).not.toContain(id);
		}
	});

	it('adds the security headers and no-store to authenticated answers', async () => {
		const id = session();
		const { response } = await run(
			request('/', { cookies: new FakeCookies({ huron_session: id }) })
		);
		expect(Object.fromEntries(response?.headers ?? [])).toMatchObject({
			'x-content-type-options': 'nosniff',
			'x-frame-options': 'DENY',
			'referrer-policy': 'same-origin',
			'cache-control': 'private, no-store'
		});
	});

	it('adds the headers to redirects and errors that loads produced', async () => {
		const id = session();
		const event = request('/', { cookies: new FakeCookies({ huron_session: id }) });
		const { response } = await run(
			event,
			() => new Response(null, { status: 303, headers: { location: '/orgs/helio' } })
		);
		expect(response?.headers.get('x-frame-options')).toBe('DENY');
		expect(response?.headers.get('cache-control')).toBe('private, no-store');
	});

	it('does not mark anonymous public pages no-store, but sign-in answers', async () => {
		const login = await run(request('/login'));
		expect(login.response?.headers.get('x-frame-options')).toBe('DENY');
		expect(login.response?.headers.has('cache-control')).toBe(false);
		const callback = await run(request('/auth/callback?code=c&state=s'));
		expect(callback.response?.headers.get('cache-control')).toBe('private, no-store');
	});

	it('uses __Host- cookie names on an https origin', async () => {
		environment.ORIGIN = 'https://huron.example.org';
		resetConfig();
		const id = session();
		const plain = request('/', { cookies: new FakeCookies({ huron_session: id }) });
		expect(isRedirect((await run(plain)).thrown)).toBe(true);
		const prefixed = request('/', { cookies: new FakeCookies({ '__Host-huron_session': id }) });
		expect((await run(prefixed)).response?.status).toBe(200);
	});

	it('turns a configuration error into a 500 that names the variable only', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		environment.HURON_API_URL = 'http://user:password@api';
		resetConfig();
		const { thrown } = await run(request('/login'));
		expect(isHttpError(thrown) && [thrown.status, thrown.body]).toEqual([
			500,
			{ message: 'HURON_API_URL must not contain credentials', code: 'CONFIG' }
		]);
		expect(JSON.stringify(thrown)).not.toContain('password');
	});
});

describe('handleError', () => {
	it('logs a reference and the error class, never the query or the error message', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const event = request('/auth/callback?code=secret-code&state=secret-state');
		const result = await handleError({
			error: new SyntaxError(`Unexpected token 'e', "eyJhbGciOi"... is not valid JSON`),
			event,
			status: 500,
			message: 'Internal Error'
		});
		expect(result).toEqual({
			message: 'Internal Error',
			id: expect.stringMatching(/^[0-9a-f-]{36}$/)
		});
		const logged = JSON.stringify(log.mock.calls);
		expect(logged).toContain('/auth/callback');
		expect(logged).toContain(result && 'id' in result ? String(result.id) : 'missing id');
		expect(logged).toContain('SyntaxError');
		for (const secret of ['secret-code', 'secret-state', 'eyJhbGciOi', 'not valid JSON']) {
			expect(logged).not.toContain(secret);
		}
	});

	it.each([
		[404, 'Not Found'],
		[405, 'Method Not Allowed']
	])('neither logs nor references its own %i', async (status, message) => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const result = await handleError({
			error: new Error(`${message}: /orgs/nowhere`),
			event: request('/orgs/nowhere'),
			status,
			message
		});
		expect(result).toEqual({ message });
		expect(log).not.toHaveBeenCalled();
	});

	it('logs only the kind of a thrown value that is not an Error', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		await handleError({
			error: 'token-shaped text',
			event: request('/orgs'),
			status: 500,
			message: 'Internal Error'
		});
		const logged = JSON.stringify(log.mock.calls);
		expect(logged).toContain('"cause":"string"');
		expect(logged).not.toContain('token-shaped text');
	});
});
