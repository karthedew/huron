// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import { sessionStore } from '$lib/server/sessions';
import {
	collectionFixture,
	fakeApi,
	jsonResponse,
	namespaceFixture,
	pageFixture,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { GET } from './+server';

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

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

function treeRequest(query: string) {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics/tree${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/tree',
		params: { catalog: 'heliophysics' }
	});
}

async function answer(query: string, routes: Record<string, FetchAnswer>) {
	const api = fakeApi(routes);
	vi.stubGlobal('fetch', api.fetch);
	const request = treeRequest(query);
	const response = await GET(request.event);
	return {
		...request,
		calls: api.calls,
		status: response.status,
		headers: response.headers,
		body: await response.json()
	};
}

const ACE = namespaceFixture({
	name: 'ace',
	path: 'solar-wind.ace',
	parent: 'solar-wind',
	namespace_count: 0,
	collection_count: 2
});

describe('GET /catalogs/[catalog]/tree', () => {
	it("answers a namespace's level as JSON that is never stored", async () => {
		const { status, headers, body } = await answer('?parent=solar-wind', {
			'/catalogs/heliophysics/namespaces?parent=solar-wind&limit=50': jsonResponse(
				pageFixture([ACE])
			),
			'/catalogs/heliophysics/namespaces/solar-wind/collections?limit=50': jsonResponse(
				pageFixture([collectionFixture({ name: 'x', identifier: 'heliophysics.solar-wind.x' })])
			)
		});
		expect(status).toBe(200);
		expect(headers.get('cache-control')).toBe('private, no-store');
		expect(headers.get('content-type')).toBe('application/json');
		expect(body).toEqual({
			parent: 'solar-wind',
			namespaces: [{ name: 'ace', path: 'solar-wind.ace', empty: false }],
			namespacesNext: null,
			collections: [{ name: 'x', identifier: 'heliophysics.solar-wind.x' }],
			collectionsNext: null
		});
	});

	it('answers the root without a parent, or with an empty one', async () => {
		for (const query of ['', '?parent=']) {
			const { body, calls } = await answer(query, {
				'/catalogs/heliophysics/namespaces?limit=50': jsonResponse(pageFixture([], 'n2'))
			});
			expect(body).toMatchObject({ parent: '', namespacesNext: 'n2', collections: [] });
			expect(calls).toHaveLength(1);
		}
	});

	it.each(['a/b', '..', 'A', 'a..b', '%2e%2e', ' a'])(
		'refuses the parent %j without calling the API',
		async (parent) => {
			const { status, body, calls, headers } = await answer(
				`?parent=${encodeURIComponent(parent)}`,
				{}
			);
			expect(status).toBe(400);
			expect(body).toEqual({ code: 'BAD_REQUEST' });
			expect(headers.get('cache-control')).toBe('private, no-store');
			expect(calls).toHaveLength(0);
		}
	);

	it.each([
		[404, 'NOT_FOUND', 404, { code: 'NOT_FOUND' }],
		[403, 'FORBIDDEN', 403, { code: 'FORBIDDEN' }],
		[503, 'DEPENDENCY_UNAVAILABLE', 503, { code: 'UNAVAILABLE' }]
	])('turns an API %i %s into a small %i', async (apiStatus, code, status, body) => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const failed = await answer('?parent=gone', {
			'/catalogs/heliophysics/namespaces?parent=gone&limit=50': problemResponse(apiStatus, code),
			'/catalogs/heliophysics/namespaces/gone/collections?limit=50': problemResponse(
				apiStatus,
				code
			)
		});
		expect(failed.status).toBe(status);
		expect(failed.body).toEqual(body);
		expect(JSON.stringify(failed.body)).not.toContain('the API explains');
	});

	it('answers an internal error with its reference only', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const failed = await answer('', {
			'/catalogs/heliophysics/namespaces?limit=50': problemResponse(500, 'INTERNAL', {
				request_id: 'req-9'
			})
		});
		expect(failed.status).toBe(500);
		expect(failed.body).toEqual({ code: 'INTERNAL', id: 'req-9' });
	});

	it('ends the session when the API no longer accepts the token', async () => {
		const { status, body, sessionId, cookies } = await answer('', {
			'/catalogs/heliophysics/namespaces?limit=50': problemResponse(401, 'TOKEN_INVALID')
		});
		expect(status).toBe(401);
		expect(body).toEqual({ code: 'UNAUTHENTICATED' });
		expect(sessionStore().user(sessionId)).toBeUndefined();
		expect(cookies.lastWrite('huron_session')?.value).toBeNull();
	});

	it('never passes on the headers of the API answer', async () => {
		const upstream = jsonResponse(pageFixture([]));
		upstream.headers.set('set-cookie', 'api=1');
		upstream.headers.set('x-api-internal', 'yes');
		const { headers } = await answer('', {
			'/catalogs/heliophysics/namespaces?limit=50': upstream
		});
		expect(headers.has('set-cookie')).toBe(false);
		expect(headers.has('x-api-internal')).toBe(false);
	});
});
