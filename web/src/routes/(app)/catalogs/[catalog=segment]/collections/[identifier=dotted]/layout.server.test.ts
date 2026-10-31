// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { collectionSummary } from '$lib/collections';
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
import { parsedObject } from '$lib/testing/json';
import { serializePageData } from '$lib/testing/page-data';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { load } from './+layout.server';

vi.mock('$env/dynamic/private', () => ({
	env: {
		ORIGIN: 'http://localhost:4173',
		HURON_API_URL: 'http://127.0.0.1:8197',
		HURON_WEB_OIDC_ISSUER: 'http://127.0.0.1:8199',
		HURON_WEB_OIDC_CLIENT_ID: 'huron-web',
		HURON_WEB_MOUNT_PREFIX: '/projects/huron'
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

const MAG = collectionFixture();
const ACE = namespaceFixture({
	id: 'n-ace',
	name: 'ace',
	path: 'solar-wind.ace',
	parent: 'solar-wind',
	identifier: 'heliophysics.solar-wind.ace',
	collections_allowed: true,
	namespace_count: 0,
	collection_count: 1
});

const COLLECTION = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024';

function collectionEvent(identifier = 'solar-wind.ace.mag-l2-2024') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics/collections/${identifier}`,
		routeId: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]',
		params: { catalog: 'heliophysics', identifier }
	});
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	const api = fakeApi({
		[COLLECTION]: jsonResponse(MAG),
		'/catalogs/heliophysics/namespaces?parent=solar-wind&limit=50': jsonResponse(
			pageFixture([ACE])
		),
		'/catalogs/heliophysics/namespaces/solar-wind/collections?limit=10': jsonResponse(
			pageFixture([])
		),
		'/catalogs/heliophysics/namespaces?parent=solar-wind.ace&limit=50': jsonResponse(
			pageFixture([])
		),
		'/catalogs/heliophysics/namespaces/solar-wind.ace/collections?limit=50': jsonResponse(
			pageFixture([MAG], 'c2')
		),
		...overrides
	});
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

describe('/catalogs/[catalog]/collections/[identifier] layout load', () => {
	it('returns the summary of the collection and the levels on the way to it', async () => {
		const api = routes();
		const data = await load(collectionEvent().event);
		expect(data.collection).toEqual(collectionSummary(MAG, '/projects/huron'));
		expect(data.collection.sharePath).toBe(
			'/projects/huron/helio/heliophysics/solar-wind/ace/mag-l2-2024'
		);
		expect(data.trail).toEqual([
			{
				parent: 'solar-wind',
				namespaces: [{ name: 'ace', path: 'solar-wind.ace', empty: false }],
				namespacesNext: null,
				collections: [],
				collectionsNext: null
			},
			{
				parent: 'solar-wind.ace',
				namespaces: [],
				namespacesNext: null,
				collections: [
					{ name: 'mag-l2-2024', identifier: 'heliophysics.solar-wind.ace.mag-l2-2024' }
				],
				collectionsNext: 'c2'
			}
		]);
		expect(api.calls).toHaveLength(5);
	});

	it('returns page data SvelteKit can send, whatever keys the metadata holds', async () => {
		const proto = collectionFixture({
			metadata: parsedObject(
				'{"title":"Proto","__proto__":{"x":1},"labels":{"__proto__":"x","mission":"proto"}}'
			),
			schema_override: parsedObject(
				'{"type":"object","properties":{"__proto__":{"type":"string"}}}'
			)
		});
		expect(() => serializePageData(proto)).toThrow('__proto__');
		routes({ [COLLECTION]: jsonResponse(proto) });
		const data = await load(collectionEvent().event);
		expect(() => serializePageData(data)).not.toThrow();
		expect(data.collection).toMatchObject({ title: 'Proto', hasOverride: true });
	});

	it('reads the levels of the trail only once the collection is there, then in parallel', async () => {
		let find = () => {};
		const found = new Promise<void>((resolve) => (find = resolve));
		const api = routes({
			[COLLECTION]: async () => {
				await found;
				return jsonResponse(MAG);
			}
		});
		const loaded = load(collectionEvent().event);
		await vi.waitFor(() => expect(api.calls).toHaveLength(1));
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(api.calls).toHaveLength(1);
		find();
		await vi.waitFor(() => expect(api.calls).toHaveLength(5));
		expect((await loaded).trail.map(({ parent }) => parent)).toEqual([
			'solar-wind',
			'solar-wind.ace'
		]);
	});

	it('reads no level for a collection that does not exist, or that a reader may not see', async () => {
		const api = routes({ [COLLECTION]: problemResponse(404, 'NOT_FOUND') });
		const outcome = await load(collectionEvent().event).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(api.calls).toHaveLength(1);
	});

	it('gives a draft no share path', async () => {
		const draft = collectionFixture({ state: 'draft', path: null, activated_at: null });
		routes({ [COLLECTION]: jsonResponse(draft) });
		const data = await load(collectionEvent().event);
		expect(data.collection).toMatchObject({ state: 'draft', sharePath: null, activatedAt: null });
	});

	it('ends the session when the API no longer accepts the token', async () => {
		routes({ [COLLECTION]: problemResponse(401, 'TOKEN_INVALID') });
		const { event, sessionId } = collectionEvent();
		const outcome = await load(event).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/login?status=expired&returnTo=%2Fcatalogs%2Fheliophysics%2Fcollections%2Fsolar-wind.ace.mag-l2-2024'
		);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it('shows the 503 page during an outage', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		routes({ [COLLECTION]: problemResponse(503, 'DEPENDENCY_UNAVAILABLE') });
		const outcome = await load(collectionEvent().event).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 503)).toBe(true);
	});
});
