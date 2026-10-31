// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { collectionRow } from '$lib/collections';
import { isFailedLevel } from '$lib/explorer';
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

const env = vi.hoisted(() => ({
	ORIGIN: 'http://localhost:4173',
	HURON_API_URL: 'http://127.0.0.1:8197',
	HURON_WEB_OIDC_ISSUER: 'http://127.0.0.1:8199',
	HURON_WEB_OIDC_CLIENT_ID: 'huron-web',
	HURON_WEB_MOUNT_PREFIX: '/projects/huron'
}));
vi.mock('$env/dynamic/private', () => ({ env }));
vi.mock('$app/environment', () => ({
	dev: false,
	browser: false,
	building: false,
	version: 'test'
}));

afterEach(async () => {
	vi.unstubAllGlobals();
	const { resetConfig } = await import('$lib/server/config');
	env.HURON_WEB_MOUNT_PREFIX = '/projects/huron';
	resetConfig();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

const DEEP = namespaceFixture({
	id: 'n-deep',
	name: 'a',
	path: 'deep.a',
	parent: 'deep',
	namespace_count: 1,
	disk_path: 'helio/heliophysics/deep/a'
});
const DEEP_A = namespaceFixture({ id: 'n-b', name: 'b', path: 'deep.a.b', parent: 'deep.a' });
const LEAF = collectionFixture({ name: 'leaf', identifier: 'heliophysics.deep.a.leaf' });

function namespaceEvent(path: string, query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics/namespaces/${path}${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]',
		params: { catalog: 'heliophysics', path }
	}).event;
}

function deepRoutes(overrides: Record<string, FetchAnswer> = {}) {
	const api = fakeApi({
		'/catalogs/heliophysics/namespaces/deep.a': jsonResponse(DEEP),
		'/catalogs/heliophysics/namespaces?parent=deep&limit=50': jsonResponse(pageFixture([DEEP])),
		'/catalogs/heliophysics/namespaces/deep/collections?limit=10': jsonResponse(pageFixture([])),
		'/catalogs/heliophysics/namespaces?parent=deep.a&limit=50': jsonResponse(
			pageFixture([DEEP_A], 'n2')
		),
		'/catalogs/heliophysics/namespaces/deep.a/collections?limit=50': jsonResponse(
			pageFixture([LEAF], 'c2')
		),
		...overrides
	});
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

describe('/catalogs/[catalog]/namespaces/[path] load', () => {
	it('returns the namespace, both lists, its share path and the trail', async () => {
		const api = deepRoutes();
		const data = await load(namespaceEvent('deep.a'));
		expect(data).toMatchObject({
			namespace: DEEP,
			sharePath: '/projects/huron/helio/heliophysics/deep/a',
			namespaces: [DEEP_A],
			namespacesNext: 'n2',
			collections: [collectionRow(LEAF)],
			collectionsNext: 'c2'
		});
		expect(data.trail.map(({ parent }) => parent)).toEqual(['deep', 'deep.a']);
		expect(data.trail[0]).toMatchObject({ parent: 'deep', collections: [] });
		expect(data.trail[1]).toEqual({
			parent: 'deep.a',
			namespaces: [{ name: 'b', path: 'deep.a.b', empty: false }],
			namespacesNext: 'n2',
			collections: [{ name: 'leaf', identifier: 'heliophysics.deep.a.leaf' }],
			collectionsNext: 'c2'
		});
		// The two first pages are the reads of the namespace's own level in the trail.
		expect(api.calls).toHaveLength(5);
	});

	it('returns page data SvelteKit can send, whatever keys the metadata holds', async () => {
		const proto = collectionFixture({
			name: 'proto-labels',
			identifier: 'heliophysics.deep.a.proto-labels',
			metadata: {
				title: 'Proto labels',
				['__proto__']: 'top level',
				labels: { ['__proto__']: 'x', mission: 'proto' }
			}
		});
		deepRoutes({
			'/catalogs/heliophysics/namespaces/deep.a/collections?limit=50': jsonResponse(
				pageFixture([proto])
			)
		});
		const data = await load(namespaceEvent('deep.a'));
		expect(() => serializePageData(data)).not.toThrow();
		expect(data.collections).toEqual([collectionRow(proto)]);
	});

	it('loads the namespace with its lists, then every level of the trail in parallel', async () => {
		let find = () => {};
		const found = new Promise<void>((resolve) => (find = resolve));
		let answer = () => {};
		const answered = new Promise<void>((resolve) => (answer = resolve));
		const after =
			(gate: Promise<void>, body: unknown): FetchAnswer =>
			async () => {
				await gate;
				return jsonResponse(body);
			};
		const api = deepRoutes({
			'/catalogs/heliophysics/namespaces/deep.a': after(found, DEEP),
			'/catalogs/heliophysics/namespaces?parent=deep&limit=50': after(
				answered,
				pageFixture([DEEP])
			),
			'/catalogs/heliophysics/namespaces/deep/collections?limit=10': after(
				answered,
				pageFixture([])
			)
		});
		const loaded = load(namespaceEvent('deep.a'));
		// The namespace and its two lists, which are also its own level of the trail.
		await vi.waitFor(() => expect(api.calls).toHaveLength(3));
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(api.calls).toHaveLength(3);
		find();
		// Once it exists, the level above it: both reads before either answers.
		await vi.waitFor(() => expect(api.calls).toHaveLength(5));
		answer();
		expect((await loaded).trail.map(({ parent }) => parent)).toEqual(['deep', 'deep.a']);
	});

	it('reads no level of the trail for a path that does not exist', async () => {
		const api = fakeApi({
			'/catalogs/heliophysics/namespaces/a.b.c.d': problemResponse(404, 'NOT_FOUND'),
			'/catalogs/heliophysics/namespaces?parent=a.b.c.d&limit=50': problemResponse(
				404,
				'NOT_FOUND'
			),
			'/catalogs/heliophysics/namespaces/a.b.c.d/collections?limit=50': problemResponse(
				404,
				'NOT_FOUND'
			)
		});
		vi.stubGlobal('fetch', api.fetch);
		const outcome = await load(namespaceEvent('a.b.c.d')).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(api.calls).toHaveLength(3);
	});

	it('pages each list by its own cursor, apart from the trail', async () => {
		const api = deepRoutes({
			'/catalogs/heliophysics/namespaces/deep.a/collections?cursor=c2&limit=50': jsonResponse(
				pageFixture([])
			)
		});
		const data = await load(namespaceEvent('deep.a', '?collections_cursor=c2'));
		expect(data.collections).toEqual([]);
		expect(data.collectionsNext).toBeNull();
		expect(data.namespaces).toEqual([DEEP_A]);
		const own = data.trail[1];
		expect(!isFailedLevel(own) && own.collections).toHaveLength(1);
		expect(api.calls).toHaveLength(6);
	});

	it('joins the configured mount prefix and the directory', async () => {
		env.HURON_WEB_MOUNT_PREFIX = '/mnt/share/';
		const { resetConfig } = await import('$lib/server/config');
		resetConfig();
		deepRoutes();
		expect((await load(namespaceEvent('deep.a'))).sharePath).toBe(
			'/mnt/share/helio/heliophysics/deep/a'
		);
	});

	it('restarts the lists when a cursor is no longer accepted', async () => {
		deepRoutes({
			'/catalogs/heliophysics/namespaces?parent=deep.a&cursor=stale&limit=50': problemResponse(
				400,
				'INVALID_CURSOR'
			),
			'/catalogs/heliophysics/namespaces/deep.a/collections?cursor=c2&limit=50': jsonResponse(
				pageFixture([])
			)
		});
		const outcome = await load(
			namespaceEvent('deep.a', '?namespaces_cursor=stale&collections_cursor=c2')
		).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/catalogs/heliophysics/namespaces/deep.a?notice=page_expired'
		);
	});

	it('ends the session once when its parallel reads all meet a 401', async () => {
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
				// SvelteKit answers with the first redirect; from then on cookie writes throw.
				await vi.waitFor(() => expect(cookies.lastWrite('huron_session')).toBeDefined());
				cookies.answer();
			}
			return problemResponse(401, 'TOKEN_INVALID');
		};
		const api = fakeApi({
			'/catalogs/heliophysics/namespaces/deep.a': unauthorized,
			'/catalogs/heliophysics/namespaces?parent=deep&limit=50': unauthorized,
			'/catalogs/heliophysics/namespaces/deep/collections?limit=10': unauthorized,
			'/catalogs/heliophysics/namespaces?parent=deep.a&limit=50': unauthorized,
			'/catalogs/heliophysics/namespaces/deep.a/collections?limit=50': unauthorized
		});
		vi.stubGlobal('fetch', api.fetch);
		const outcome = await load(event).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/login?status=expired&returnTo=%2Fcatalogs%2Fheliophysics%2Fnamespaces%2Fdeep.a'
		);
		// The namespace and its two lists; the trail waits for a namespace that never came.
		await vi.waitFor(() => expect(answered).toBe(3));
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(deletes).toHaveBeenCalledOnce();
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it('shows a namespace that does not exist as not found', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/catalogs/heliophysics/namespaces/nope': problemResponse(404, 'NOT_FOUND'),
				'/catalogs/heliophysics/namespaces?parent=nope&limit=50': problemResponse(404, 'NOT_FOUND'),
				'/catalogs/heliophysics/namespaces/nope/collections?limit=50': problemResponse(
					404,
					'NOT_FOUND'
				)
			}).fetch
		);
		const outcome = await load(namespaceEvent('nope')).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
	});
});
