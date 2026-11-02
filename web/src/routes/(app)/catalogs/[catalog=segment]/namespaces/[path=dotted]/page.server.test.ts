// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { collectionRow } from '$lib/collections';
import {
	collectionFixture,
	fakeApi,
	jsonResponse,
	namespaceFixture,
	pageFixture,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { sessionStore } from '$lib/server/sessions';
import { serializePageData } from '$lib/testing/page-data';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { load } from './+page.server';

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
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

const CHILD = namespaceFixture({ id: 'n-b', name: 'b', path: 'deep.a.b', parent: 'deep.a' });
const LEAF = collectionFixture({ name: 'leaf', identifier: 'heliophysics.deep.a.leaf' });
const DEFAULT_SORT = { sort: 'name', order: 'asc' };
const NAMESPACES = '/catalogs/heliophysics/namespaces?parent=deep.a&limit=20&sort=name&order=asc';
const COLLECTIONS =
	'/catalogs/heliophysics/namespaces/deep.a/collections?limit=20&sort=name&order=asc';

function namespaceEvent(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics/namespaces/deep.a${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]',
		params: { catalog: 'heliophysics', path: 'deep.a' }
	}).event;
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	const client = fakeApi({
		[NAMESPACES]: jsonResponse(pageFixture([CHILD], 'n2')),
		[COLLECTIONS]: jsonResponse(pageFixture([LEAF], 'c2')),
		...overrides
	});
	vi.stubGlobal('fetch', client.fetch);
	return client;
}

describe('namespace browse load', () => {
	it('reads only the two twenty-row lists and leaves common data to the layout', async () => {
		const client = routes();
		const data = await load(namespaceEvent());
		expect(data).toEqual({
			namespaces: [CHILD],
			namespacesNext: 'n2',
			namespaceSort: DEFAULT_SORT,
			collections: [collectionRow(LEAF)],
			collectionsNext: 'c2',
			collectionSort: DEFAULT_SORT
		});
		expect(client.calls).toHaveLength(2);
		expect(() => serializePageData(data)).not.toThrow();
	});

	it('sends each list its own sort and cursor without sorting the returned page locally', async () => {
		const later = collectionFixture({ id: 'c2', name: 'a', identifier: 'heliophysics.deep.a.a' });
		routes({
			'/catalogs/heliophysics/namespaces?parent=deep.a&cursor=n2&limit=20&sort=created_at&order=desc':
				jsonResponse(pageFixture([])),
			'/catalogs/heliophysics/namespaces/deep.a/collections?cursor=c2&limit=20&sort=created_by&order=asc':
				jsonResponse(pageFixture([LEAF, later]))
		});
		const data = await load(
			namespaceEvent(
				'?namespaces_cursor=n2&namespaces_sort=created_at&namespaces_order=desc&collections_cursor=c2&collections_sort=created_by&collections_order=asc'
			)
		);
		expect(data.namespaces).toEqual([]);
		expect(data.namespacesNext).toBeNull();
		expect(data.namespaceSort).toEqual({ sort: 'created_at', order: 'desc' });
		expect(data.collections.map(({ name }) => name)).toEqual(['leaf', 'a']);
		expect(data.collectionSort).toEqual({ sort: 'created_by', order: 'asc' });
	});

	it('keeps arbitrary metadata keys off serialized page data', async () => {
		const proto = collectionFixture({
			metadata: {
				title: 'Proto labels',
				['__proto__']: 'top level',
				labels: { ['__proto__']: 'x' }
			}
		});
		routes({ [COLLECTIONS]: jsonResponse(pageFixture([proto])) });
		const data = await load(namespaceEvent());
		expect(() => serializePageData(data)).not.toThrow();
		expect(data.collections).toEqual([collectionRow(proto)]);
	});

	it('starts both reads before either answers', async () => {
		let release = () => {};
		const waiting = new Promise<void>((resolve) => {
			release = resolve;
		});
		const answer: FetchAnswer = async () => {
			await waiting;
			return jsonResponse(pageFixture([]));
		};
		const client = routes({ [NAMESPACES]: answer, [COLLECTIONS]: answer });
		const loaded = load(namespaceEvent());
		await vi.waitFor(() => expect(client.calls).toHaveLength(2));
		release();
		expect((await loaded).collections).toEqual([]);
	});

	it('restarts expired cursors while retaining the selected ordering', async () => {
		routes({
			'/catalogs/heliophysics/namespaces?parent=deep.a&cursor=stale&limit=20&sort=created_at&order=desc':
				problemResponse(400, 'INVALID_CURSOR'),
			'/catalogs/heliophysics/namespaces/deep.a/collections?cursor=c2&limit=20&sort=name&order=asc':
				jsonResponse(pageFixture([]))
		});
		const outcome = await load(
			namespaceEvent(
				'?namespaces_cursor=stale&collections_cursor=c2&namespaces_sort=created_at&namespaces_order=desc'
			)
		).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/catalogs/heliophysics/namespaces/deep.a?namespaces_sort=created_at&namespaces_order=desc&notice=page_expired'
		);
	});

	it('ends the session once when both parallel reads meet a401', async () => {
		const { event, cookies, sessionId } = signedInLoadEvent({
			url: 'http://localhost:4173/catalogs/heliophysics/namespaces/deep.a',
			routeId: '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]',
			params: { catalog: 'heliophysics', path: 'deep.a' }
		});
		const deletes = vi.spyOn(cookies, 'delete');
		let answered = 0;
		const unauthorized: FetchAnswer = async () => {
			answered += 1;
			if (answered > 1) {
				await vi.waitFor(() => expect(cookies.lastWrite('huron_session')).toBeDefined());
				cookies.answer();
			}
			return problemResponse(401, 'TOKEN_INVALID');
		};
		routes({ [NAMESPACES]: unauthorized, [COLLECTIONS]: unauthorized });
		const outcome = await load(event).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/login?status=expired&returnTo=%2Fcatalogs%2Fheliophysics%2Fnamespaces%2Fdeep.a'
		);
		await vi.waitFor(() => expect(answered).toBe(2));
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(deletes).toHaveBeenCalledOnce();
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it('returns not found when the namespace listing is concealed or missing', async () => {
		routes({
			[NAMESPACES]: problemResponse(404, 'NOT_FOUND'),
			[COLLECTIONS]: problemResponse(404, 'NOT_FOUND')
		});
		const outcome = await load(namespaceEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
	});
});
