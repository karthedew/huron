// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { errorCopy } from '$lib/error-copy';
import {
	fakeFetch,
	jsonResponse,
	pageFixture,
	whoamiFixture,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { fakeRequestEvent, fakeUser } from '$lib/testing/events';
import { FakeCookies } from '$lib/testing/fake-cookies';
import {
	FAILURE_COPY,
	api,
	degrade,
	fail,
	failureJson,
	failureResponse,
	firstPagePath,
	guarded,
	hasCursor,
	requireUser,
	settled
} from './guard';
import { HuronApiError } from './huron-api';
import { sessionStore } from './sessions';

vi.mock('$env/dynamic/private', () => ({
	env: {
		ORIGIN: 'http://localhost:4173',
		HURON_API_URL: 'http://127.0.0.1:8197',
		HURON_WEB_OIDC_ISSUER: 'http://127.0.0.1:8199',
		HURON_WEB_OIDC_CLIENT_ID: 'huron-web'
	}
}));
vi.mock('$app/environment', () => ({
	dev: false,
	browser: false,
	building: false,
	version: 'test'
}));

function signedIn(token = 'huron-token') {
	const { id } = sessionStore().create({
		huronToken: token,
		tokenExpiresAt: new Date(Date.now() + 3_600_000).toISOString(),
		subject: 'sub-erin',
		name: 'Erin Example',
		groups: ['helio-readers']
	});
	return { id, cookies: new FakeCookies({ huron_session: id }) };
}

function event(path: string, cookies = new FakeCookies(), user = fakeUser()) {
	return fakeRequestEvent({
		url: `http://localhost:4173${path}`,
		routeId: null,
		params: {},
		cookies,
		user
	});
}

function thrown(run: () => unknown): unknown {
	try {
		run();
	} catch (outcome) {
		return outcome;
	}
	throw new Error('expected a throw');
}

function redirectOf(run: () => unknown): { status: number; location: string } {
	const outcome = thrown(run);
	if (!isRedirect(outcome)) throw new Error('expected a redirect');
	return { status: outcome.status, location: outcome.location };
}

function httpErrorOf(run: () => unknown): { status: number; body: App.Error } {
	const outcome = thrown(run);
	if (!isHttpError(outcome)) throw new Error('expected an HTTP error');
	return { status: outcome.status, body: outcome.body };
}

function stubFetch(...answers: FetchAnswer[]) {
	const fake = fakeFetch(...answers);
	vi.stubGlobal('fetch', fake.fetch);
	return fake.calls;
}

/** Silence and capture the error log. */
function errorLog() {
	return vi.spyOn(console, 'error').mockImplementation(() => undefined);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

describe('api', () => {
	it('calls the API with the token of the session named by the cookie', async () => {
		const calls = stubFetch(jsonResponse(whoamiFixture()));
		const { cookies } = signedIn('token-of-erin');
		await api(event('/', cookies)).whoami();
		expect(calls[0].url).toBe('http://127.0.0.1:8197/api/v1/auth/whoami');
		expect(new Headers(calls[0].init?.headers).get('authorization')).toBe('Bearer token-of-erin');
	});

	it('returns one client per request that shares GET answers', async () => {
		const calls = stubFetch(jsonResponse(pageFixture([])));
		const { cookies } = signedIn();
		const request = event('/', cookies);
		const client = api(request);
		expect(api(request)).toBe(client);
		await Promise.all([
			client.organizations({ limit: 500 }),
			api(request).organizations({ limit: 500 })
		]);
		expect(calls).toHaveLength(1);
		expect(api(event('/', cookies))).not.toBe(client);
	});

	it('sends a request without a session to the login page', () => {
		expect(redirectOf(() => api(event('/orgs/helio?x=1')))).toEqual({
			status: 303,
			location: '/login?returnTo=%2Forgs%2Fhelio%3Fx%3D1'
		});
	});

	it('marks the redirect as expired when the cookie names a dead session', () => {
		const cookies = new FakeCookies({ huron_session: 'gone' });
		expect(redirectOf(() => api(event('/', cookies))).location).toBe(
			'/login?returnTo=%2F&status=expired'
		);
	});
});

describe('requireUser', () => {
	it('returns the signed-in user or sends the request to sign in', () => {
		const user = fakeUser();
		expect(requireUser(event('/', new FakeCookies(), user))).toBe(user);
		const anonymous = fakeRequestEvent({
			url: 'http://localhost:4173/account',
			routeId: null,
			params: {}
		});
		expect(redirectOf(() => requireUser(anonymous)).location).toBe('/login?returnTo=%2Faccount');
	});
});

describe('fail', () => {
	const apiError = (status: number, code: string, requestId?: string) =>
		new HuronApiError({
			status,
			code,
			title: code,
			detail: 'API detail',
			context: { a: 1 },
			requestId
		});

	it('rethrows anything that is not an API error', () => {
		const bug = new TypeError('bug');
		expect(thrown(() => fail(event('/'), bug))).toBe(bug);
	});

	it('ends the session on a 401 and asks the user to sign in again', () => {
		const { id, cookies } = signedIn();
		const outcome = redirectOf(() =>
			fail(event('/orgs/helio?q=1', cookies), apiError(401, 'TOKEN_INVALID'))
		);
		expect(outcome).toEqual({
			status: 303,
			location: '/login?status=expired&returnTo=%2Forgs%2Fhelio%3Fq%3D1'
		});
		expect(sessionStore().user(id)).toBeUndefined();
		expect(cookies.lastWrite('huron_session')?.value).toBeNull();
	});

	it('ends the session once when parallel loads of one request each meet the 401', () => {
		const { id, cookies } = signedIn();
		const request = event('/orgs/helio', cookies);
		const first = redirectOf(() => fail(request, apiError(401, 'TOKEN_INVALID')));
		// The first redirect lets SvelteKit answer; from then on it refuses cookie writes.
		cookies.answer();
		expect(redirectOf(() => fail(request, apiError(401, 'TOKEN_INVALID')))).toEqual(first);
		expect(sessionStore().user(id)).toBeUndefined();
		expect(cookies.writes.filter(({ name }) => name === 'huron_session')).toHaveLength(1);
	});

	it.each([
		[403, 'FORBIDDEN', 403, FAILURE_COPY.forbidden],
		[404, 'NOT_FOUND', 404, FAILURE_COPY.notFound],
		[422, 'REQUEST_INVALID', 400, FAILURE_COPY.badRequest],
		[409, 'STATE_CONFLICT', 400, FAILURE_COPY.badRequest],
		[400, 'NAME_INVALID', 400, FAILURE_COPY.badRequest]
	])('maps %i %s to a %i with fixed copy and logs nothing', (status, code, expected, message) => {
		const log = errorLog();
		const outcome = httpErrorOf(() => fail(event('/'), apiError(status, code)));
		expect(outcome).toEqual({ status: expected, body: { message, code } });
		expect(JSON.stringify(outcome.body)).not.toContain('API detail');
		expect(log).not.toHaveBeenCalled();
	});

	it.each([
		[502, 'HTTP'],
		[500, 'INTERNAL']
	])('maps %i %s to a 500 with fixed copy and a logged reference', (status, code) => {
		const log = errorLog();
		const outcome = httpErrorOf(() =>
			fail(event('/orgs/helio?q=private-query'), apiError(status, code))
		);
		expect(outcome).toEqual({
			status: 500,
			body: { message: FAILURE_COPY.internal, code, id: expect.stringMatching(UUID) }
		});
		expect(log).toHaveBeenCalledExactlyOnceWith('huron-web API call failed', {
			id: outcome.body.id,
			status,
			code,
			title: code,
			path: '/orgs/helio',
			requestId: null
		});
		const logged = JSON.stringify(log.mock.calls);
		for (const hidden of ['API detail', 'private-query', '"a":1']) {
			expect(logged).not.toContain(hidden);
		}
	});

	it.each(['DEPENDENCY_UNAVAILABLE', 'API_UNREACHABLE'])(
		'maps 503 %s to a 503 with fixed copy that is logged but shows no reference',
		(code) => {
			const log = errorLog();
			const outcome = httpErrorOf(() =>
				fail(event('/orgs/helio?q=private-query'), apiError(503, code, 'req-7'))
			);
			expect(outcome).toEqual({ status: 503, body: { message: FAILURE_COPY.unavailable, code } });
			expect(log).toHaveBeenCalledExactlyOnceWith('huron-web API call failed', {
				id: 'req-7',
				status: 503,
				code,
				title: code,
				path: '/orgs/helio',
				requestId: 'req-7'
			});
			const logged = JSON.stringify(log.mock.calls);
			for (const hidden of ['API detail', 'private-query', '"a":1']) {
				expect(logged).not.toContain(hidden);
			}
		}
	);

	it('uses the API request id of a failure as the reference in both logs', () => {
		const log = errorLog();
		const outcome = httpErrorOf(() => fail(event('/'), apiError(500, 'INTERNAL', 'req-42')));
		expect(outcome).toEqual({
			status: 500,
			body: { message: FAILURE_COPY.internal, code: 'INTERNAL', id: 'req-42' }
		});
		expect(log).toHaveBeenCalledExactlyOnceWith(
			'huron-web API call failed',
			expect.objectContaining({ id: 'req-42', requestId: 'req-42' })
		);
	});

	it('logs a malformed answer and an unreachable API and references the first', async () => {
		const log = errorLog();
		const { cookies } = signedIn();
		stubFetch(
			new Response('<html>a proxy page</html>', { headers: { 'content-type': 'text/html' } }),
			new TypeError('fetch failed')
		);
		const outcomes: Array<{ status: number; body: App.Error }> = [];
		for (const path of ['/orgs', '/orgs/helio']) {
			const request = event(path, cookies);
			const failure = await api(request)
				.organizations()
				.then(
					() => undefined,
					(rejection: unknown) => rejection
				);
			outcomes.push(httpErrorOf(() => fail(request, failure)));
		}
		expect(outcomes).toEqual([
			{
				status: 500,
				body: { message: FAILURE_COPY.internal, code: 'HTTP', id: expect.stringMatching(UUID) }
			},
			{
				status: 503,
				body: { message: FAILURE_COPY.unavailable, code: 'API_UNREACHABLE' }
			}
		]);
		expect(log.mock.calls).toEqual([
			[
				'huron-web API call failed',
				expect.objectContaining({ id: outcomes[0].body.id, status: 502, path: '/orgs' })
			],
			[
				'huron-web API call failed',
				expect.objectContaining({
					id: expect.stringMatching(UUID),
					status: 503,
					code: 'API_UNREACHABLE',
					path: '/orgs/helio'
				})
			]
		]);
	});

	it('restarts a list whose cursor the API no longer accepts', () => {
		const log = errorLog();
		const path = '/catalogs/x/namespaces/a?namespaces_cursor=n&collections_cursor=c&q=1';
		expect(redirectOf(() => fail(event(path), apiError(400, 'INVALID_CURSOR')))).toEqual({
			status: 303,
			location: '/catalogs/x/namespaces/a?q=1&notice=page_expired'
		});
		expect(log).not.toHaveBeenCalled();
		expect(
			redirectOf(() => fail(event('/orgs?cursor=x'), apiError(500, 'INTERNAL'))).location
		).toBe('/orgs?notice=page_expired');
		expect(log).toHaveBeenCalledExactlyOnceWith(
			'huron-web API call failed',
			expect.objectContaining({ status: 500, code: 'INTERNAL', path: '/orgs' })
		);
	});
});

describe('cursor helpers', () => {
	it('recognizes cursor parameters and drops them for the first page', () => {
		expect(hasCursor(new URL('http://x/a?cursor=1'))).toBe(true);
		expect(hasCursor(new URL('http://x/a?files_cursor=1'))).toBe(true);
		expect(hasCursor(new URL('http://x/a?q=cursor'))).toBe(false);
		expect(firstPagePath(new URL('http://x/a?cursor=1&notice=old&q=w'))).toBe(
			'/a?q=w&notice=page_expired'
		);
	});
});

describe('FAILURE_COPY', () => {
	it('says what the error pages say for the same statuses, in the fixed words of §4.5', () => {
		expect(FAILURE_COPY).toEqual({
			badRequest: errorCopy(400).heading,
			forbidden: errorCopy(403).heading,
			notFound: errorCopy(404).heading,
			unavailable: errorCopy(503).heading,
			internal: errorCopy(500).heading
		});
		expect(FAILURE_COPY.notFound).toBe("Not found, or you don't have access.");
		expect(FAILURE_COPY.unavailable).toBe("The Huron service isn't responding.");
	});
});

describe('settled', () => {
	it('captures outcomes instead of throwing', async () => {
		expect(await settled(Promise.resolve(1))).toEqual({ ok: true, value: 1 });
		const failure = new HuronApiError({ status: 401, code: 'TOKEN_INVALID', title: 't' });
		expect(await settled(Promise.reject(failure))).toEqual({ ok: false, failure });
	});
});

describe('guarded', () => {
	it('passes a successful read through', async () => {
		expect(await guarded(event('/'), Promise.resolve('value'))).toBe('value');
	});

	it('turns a failed read into the page outcome', async () => {
		const failure = new HuronApiError({ status: 404, code: 'NOT_FOUND', title: 'n' });
		const outcome = await guarded(event('/orgs/x'), Promise.reject(failure)).catch(
			(thrown: unknown) => thrown
		);
		expect(isHttpError(outcome, 404)).toBe(true);
	});
});

describe('degrade', () => {
	const unavailable = new HuronApiError({
		status: 503,
		code: 'DEPENDENCY_UNAVAILABLE',
		title: 'Dependency unavailable',
		detail: 'private detail',
		requestId: 'req-7'
	});

	it('logs an API failure by its fixed vocabulary and lets the page go on', () => {
		const log = errorLog();
		expect(degrade(event('/account?x=1'), unavailable)).toBeUndefined();
		expect(log).toHaveBeenCalledOnce();
		const [, entry] = log.mock.calls[0];
		expect(entry).toEqual({
			id: 'req-7',
			status: 503,
			code: 'DEPENDENCY_UNAVAILABLE',
			title: 'Dependency unavailable',
			path: '/account',
			requestId: 'req-7'
		});
		expect(JSON.stringify(log.mock.calls)).not.toContain('private detail');
	});

	it('still ends the session when the Huron token is no longer accepted', () => {
		const { id, cookies } = signedIn();
		const failure = new HuronApiError({ status: 401, code: 'TOKEN_INVALID', title: 't' });
		const outcome = redirectOf(() => degrade(event('/account', cookies), failure));
		expect(outcome.location).toBe('/login?status=expired&returnTo=%2Faccount');
		expect(sessionStore().user(id)).toBeUndefined();
	});

	it('rethrows anything that is not an API error', () => {
		const bug = new TypeError('bug');
		expect(thrown(() => degrade(event('/'), bug))).toBe(bug);
	});

	it('logs a failure that a layout and a page share once, under one reference', () => {
		const log = errorLog();
		const shared = new HuronApiError({ status: 500, code: 'INTERNAL', title: 'Internal' });
		const request = event('/account');
		degrade(request, shared);
		const page = httpErrorOf(() => fail(request, shared));
		expect(log).toHaveBeenCalledOnce();
		const [, entry] = log.mock.calls[0];
		expect(entry).toMatchObject({ id: page.body.id });
		expect(page.body.id).toMatch(UUID);
	});
});

describe('failureResponse', () => {
	const apiError = (status: number, code: string, requestId?: string) =>
		new HuronApiError({ status, code, title: code, detail: 'API detail', requestId });

	async function answer(response: Response) {
		return {
			status: response.status,
			body: await response.json(),
			cacheControl: response.headers.get('cache-control')
		};
	}

	it('ends the session on a 401 and answers like the hook does without one', async () => {
		const { id, cookies } = signedIn();
		const response = failureResponse(
			event('/catalogs/h/tree', cookies),
			apiError(401, 'TOKEN_INVALID')
		);
		expect(await answer(response)).toEqual({
			status: 401,
			body: { code: 'UNAUTHENTICATED' },
			cacheControl: 'private, no-store'
		});
		expect(sessionStore().user(id)).toBeUndefined();
		expect(cookies.lastWrite('huron_session')?.value).toBeNull();
	});

	it.each([
		[403, 'FORBIDDEN', 403, 'FORBIDDEN'],
		[404, 'NOT_FOUND', 404, 'NOT_FOUND'],
		[400, 'INVALID_CURSOR', 400, 'BAD_REQUEST'],
		[422, 'REQUEST_INVALID', 400, 'BAD_REQUEST']
	])('maps %i %s to %i %s without a log entry', async (status, code, expected, body) => {
		const log = errorLog();
		const response = failureResponse(event('/catalogs/h/tree'), apiError(status, code));
		expect(await answer(response)).toEqual({
			status: expected,
			body: { code: body },
			cacheControl: 'private, no-store'
		});
		expect(log).not.toHaveBeenCalled();
	});

	it('logs an outage and answers 503 without detail', async () => {
		const log = errorLog();
		const response = failureResponse(
			event('/catalogs/h/tree?parent=a'),
			apiError(503, 'API_UNREACHABLE', 'req-3')
		);
		expect(await answer(response)).toEqual({
			status: 503,
			body: { code: 'UNAVAILABLE' },
			cacheControl: 'private, no-store'
		});
		expect(log).toHaveBeenCalledExactlyOnceWith('huron-web API call failed', {
			id: 'req-3',
			status: 503,
			code: 'API_UNREACHABLE',
			title: 'API_UNREACHABLE',
			path: '/catalogs/h/tree',
			requestId: 'req-3'
		});
	});

	it('logs an internal error and answers its reference', async () => {
		const log = errorLog();
		const response = failureResponse(event('/catalogs/h/tree'), apiError(502, 'HTTP'));
		const { status, body } = await answer(response);
		expect(status).toBe(500);
		expect(body).toEqual({ code: 'INTERNAL', id: expect.stringMatching(UUID) });
		expect(JSON.stringify(body)).not.toContain('API detail');
		expect(log).toHaveBeenCalledOnce();
	});

	it('rethrows anything that is not an API error', () => {
		const bug = new TypeError('bug');
		expect(thrown(() => failureResponse(event('/'), bug))).toBe(bug);
	});

	it('writes small JSON answers that are never stored', async () => {
		expect(await answer(failureJson(400, { code: 'BAD_REQUEST' }))).toEqual({
			status: 400,
			body: { code: 'BAD_REQUEST' },
			cacheControl: 'private, no-store'
		});
	});
});
