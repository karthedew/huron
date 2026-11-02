// @vitest-environment node
import { isHttpError } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	auditFixture,
	collectionFixture,
	fakeApi,
	jsonResponse,
	pageFixture,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
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
	vi.restoreAllMocks();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

const ID = '0192f2a4-0000-7000-8000-000000000401';
const COLLECTION = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024';
const ENTRIES = [
	auditFixture({ id: 9 }),
	auditFixture({
		id: 8,
		action: 'collection.create',
		detail: { identifier: 'heliophysics.solar-wind.ace.mag-l2-2024' }
	})
];

function activityEvent(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/activity${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/activity',
		params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' }
	}).event;
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	const api = fakeApi({
		[COLLECTION]: jsonResponse(collectionFixture()),
		[`/collections/${ID}/log?limit=50`]: jsonResponse(pageFixture(ENTRIES, 'older')),
		...overrides
	});
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

describe('/catalogs/[catalog]/collections/[identifier]/activity load', () => {
	it("returns the newest entries of the collection's log and the cursor of older ones", async () => {
		const api = routes();
		const data = await load(activityEvent());
		expect(data).toEqual({ entries: ENTRIES, nextCursor: 'older', schemas: {} });
		expect(() => serializePageData(data)).not.toThrow();
		expect(api.calls).toHaveLength(2);
	});

	it('reads the page its cursor names', async () => {
		routes({
			[`/collections/${ID}/log?cursor=older&limit=50`]: jsonResponse(pageFixture([]))
		});
		expect(await load(activityEvent('?cursor=older'))).toEqual({
			entries: [],
			nextCursor: null,
			schemas: {}
		});
	});

	it("reads a draft's log too", async () => {
		const api = routes({
			[COLLECTION]: jsonResponse(collectionFixture({ state: 'draft', path: null }))
		});
		expect((await load(activityEvent())).entries).toEqual(ENTRIES);
		expect(api.calls).toHaveLength(2);
	});

	it('shows the 503 page during an outage', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		routes({ [`/collections/${ID}/log?limit=50`]: problemResponse(503, 'API_UNREACHABLE') });
		const outcome = await load(activityEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 503)).toBe(true);
	});
});
