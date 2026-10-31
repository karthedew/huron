// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { isFailedLevel, pathPrefixes } from '$lib/explorer';
import {
	TEST_API,
	collectionFixture,
	fakeApi,
	hangingAnswer,
	jsonResponse,
	namespaceFixture,
	pageFixture,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { LIST_PAGE_SIZE } from '$lib/paging';
import { ANCESTOR_COLLECTIONS, TRAIL_CONCURRENCY, loadLevel, loadTrail } from './explorer';
import { HuronApi } from './huron-api';

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
	vi.restoreAllMocks();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

/** The request of a namespace page, for the trail's logging and its expired session. */
function pageEvent() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/catalogs/heliophysics/namespaces/deep.a',
		routeId: '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]',
		params: { catalog: 'heliophysics', path: 'deep.a' }
	});
}

function client(routes: Record<string, FetchAnswer>) {
	const api = fakeApi(routes);
	return {
		calls: api.calls,
		client: new HuronApi({
			baseUrl: TEST_API.replace('/api/v1', ''),
			token: 'huron-token',
			fetch: api.fetch,
			timeoutMs: 1000,
			memoize: true
		})
	};
}

const DEEP = namespaceFixture({ name: 'a', path: 'deep.a', parent: 'deep', namespace_count: 1 });
const DEEP_A = namespaceFixture({ name: 'b', path: 'deep.a.b', parent: 'deep.a' });
const LEAF = collectionFixture({ name: 'leaf', identifier: 'heliophysics.deep.a.leaf' });

describe('loadLevel', () => {
	it('reads only namespaces at the catalog root', async () => {
		const { client: api, calls } = client({
			'/catalogs/heliophysics/namespaces?limit=50': jsonResponse(pageFixture([DEEP], 'n2'))
		});
		expect(await loadLevel(api, 'heliophysics', '')).toEqual({
			parent: '',
			namespaces: [{ name: 'a', path: 'deep.a', empty: false }],
			namespacesNext: 'n2',
			collections: [],
			collectionsNext: null
		});
		expect(calls).toHaveLength(1);
	});

	it("reads a namespace's first pages of namespaces and collections", async () => {
		const { client: api } = client({
			'/catalogs/heliophysics/namespaces?parent=deep.a&limit=50': jsonResponse(
				pageFixture([DEEP_A])
			),
			'/catalogs/heliophysics/namespaces/deep.a/collections?limit=50': jsonResponse(
				pageFixture([LEAF], 'c2')
			)
		});
		expect(await loadLevel(api, 'heliophysics', 'deep.a')).toEqual({
			parent: 'deep.a',
			namespaces: [{ name: 'b', path: 'deep.a.b', empty: false }],
			namespacesNext: null,
			collections: [{ name: 'leaf', identifier: 'heliophysics.deep.a.leaf' }],
			collectionsNext: 'c2'
		});
	});
});

describe('loadTrail', () => {
	it('loads every level on the way in parallel and shares reads with the page', async () => {
		let release = () => {};
		const held = new Promise<void>((resolve) => (release = resolve));
		const later =
			(body: unknown): FetchAnswer =>
			async () => {
				await held;
				return jsonResponse(body);
			};
		const { client: api, calls } = client({
			'/catalogs/heliophysics/namespaces?parent=deep&limit=50': later(pageFixture([DEEP])),
			'/catalogs/heliophysics/namespaces/deep/collections?limit=10': later(pageFixture([])),
			'/catalogs/heliophysics/namespaces?parent=deep.a&limit=50': later(pageFixture([DEEP_A])),
			'/catalogs/heliophysics/namespaces/deep.a/collections?limit=50': later(pageFixture([LEAF]))
		});
		const trail = loadTrail(pageEvent().event, api, 'heliophysics', 'deep.a');
		// Every read is on its way before the first answer arrives.
		await vi.waitFor(() => expect(calls).toHaveLength(4));
		// The page's own first page of the same namespace is the trail's read.
		const pageList = api.namespaceCollections('heliophysics', 'deep.a', {
			cursor: null,
			limit: 50
		});
		release();
		const levels = await trail;
		expect(levels.map(({ parent }) => parent)).toEqual(['deep', 'deep.a']);
		expect(levels.some(isFailedLevel)).toBe(false);
		const own = levels[1];
		expect(!isFailedLevel(own) && own.collections).toEqual([
			{ name: 'leaf', identifier: 'heliophysics.deep.a.leaf' }
		]);
		expect((await pageList).items).toEqual([LEAF]);
		expect(calls).toHaveLength(4);
	});

	it('lists fewer collections in the levels above the page’s own namespace', async () => {
		// The explorer shows only names, but the API lists each collection whole.
		const { client: api, calls } = client({
			'/catalogs/heliophysics/namespaces?parent=deep&limit=50': jsonResponse(pageFixture([DEEP])),
			'/catalogs/heliophysics/namespaces/deep/collections?limit=10': jsonResponse(
				pageFixture(
					[collectionFixture({ name: 'top', identifier: 'heliophysics.deep.top' })],
					'c11'
				)
			),
			'/catalogs/heliophysics/namespaces?parent=deep.a&limit=50': jsonResponse(
				pageFixture([DEEP_A])
			),
			'/catalogs/heliophysics/namespaces/deep.a/collections?limit=50': jsonResponse(
				pageFixture([LEAF])
			)
		});
		const levels = await loadTrail(pageEvent().event, api, 'heliophysics', 'deep.a');
		expect(calls.map(({ url }) => url.slice(TEST_API.length)).sort()).toEqual([
			`/catalogs/heliophysics/namespaces/deep.a/collections?limit=${LIST_PAGE_SIZE}`,
			`/catalogs/heliophysics/namespaces/deep/collections?limit=${ANCESTOR_COLLECTIONS}`,
			`/catalogs/heliophysics/namespaces?parent=deep&limit=${LIST_PAGE_SIZE}`,
			`/catalogs/heliophysics/namespaces?parent=deep.a&limit=${LIST_PAGE_SIZE}`
		]);
		// Its "More…" then leads past the ten it shows.
		expect(levels[0]).toMatchObject({
			parent: 'deep',
			collections: [{ name: 'top', identifier: 'heliophysics.deep.top' }],
			collectionsNext: 'c11'
		});
	});

	it('has no levels for the catalog root', async () => {
		const { client: api, calls } = client({});
		expect(await loadTrail(pageEvent().event, api, 'heliophysics', '')).toEqual([]);
		expect(calls).toHaveLength(0);
	});

	it('never has more than a few levels in flight, however deep the path', async () => {
		// 120 levels: the deepest path an identifier of 255 bytes holds.
		const path = Array.from({ length: 120 }, () => 'z').join('.');
		let inFlight = 0;
		let most = 0;
		const api = new HuronApi({
			baseUrl: TEST_API.replace('/api/v1', ''),
			token: 'huron-token',
			timeoutMs: 1000,
			memoize: true,
			fetch: async () => {
				inFlight += 1;
				most = Math.max(most, inFlight);
				await new Promise((resolve) => setTimeout(resolve, 1));
				inFlight -= 1;
				return jsonResponse(pageFixture([]));
			}
		});
		const levels = await loadTrail(pageEvent().event, api, 'heliophysics', path);
		expect(levels).toHaveLength(120);
		expect(most).toBeLessThanOrEqual(2 * TRAIL_CONCURRENCY);
		expect(most).toBeGreaterThan(1);
	});

	it('gives a level whose read fails as failed, logs it, and still loads the others', async () => {
		const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
		const { client: api } = client({
			'/catalogs/heliophysics/namespaces?parent=deep&limit=50': jsonResponse(pageFixture([DEEP])),
			'/catalogs/heliophysics/namespaces/deep/collections?limit=10': problemResponse(
				503,
				'DEPENDENCY_UNAVAILABLE'
			),
			'/catalogs/heliophysics/namespaces?parent=deep.a&limit=50': jsonResponse(
				pageFixture([DEEP_A])
			),
			'/catalogs/heliophysics/namespaces/deep.a/collections?limit=50': jsonResponse(
				pageFixture([LEAF])
			)
		});
		const levels = await loadTrail(pageEvent().event, api, 'heliophysics', 'deep.a');
		expect(levels[0]).toEqual({ parent: 'deep', failed: true });
		expect(isFailedLevel(levels[1])).toBe(false);
		expect(logged).toHaveBeenCalledWith(
			'huron-web API call failed',
			expect.objectContaining({ status: 503, code: 'DEPENDENCY_UNAVAILABLE' })
		);
	});

	it('still ends the session where the Huron token expired', async () => {
		const { client: api } = client({
			'/catalogs/heliophysics/namespaces?parent=deep&limit=50': problemResponse(
				401,
				'TOKEN_INVALID'
			),
			'/catalogs/heliophysics/namespaces/deep/collections?limit=50': hangingAnswer
		});
		const { event, cookies } = pageEvent();
		const outcome = await loadTrail(event, api, 'heliophysics', 'deep').catch(
			(thrown: unknown) => thrown
		);
		expect(isRedirect(outcome) && outcome.location).toMatch(/^\/login\?status=expired/);
		expect(cookies.lastWrite('huron_session')?.value).toBeNull();
	});
});

describe('pathPrefixes', () => {
	it('names every level on the way, the path itself included', () => {
		expect(pathPrefixes('deep.a.b')).toEqual(['deep', 'deep.a', 'deep.a.b']);
	});
});
