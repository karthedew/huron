// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	auditFixture,
	fakeApi,
	jsonResponse,
	pageFixture,
	problemResponse,
	schemaFixture,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
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

const BASE = '0192f2a4-0000-7000-8000-000000000201';
const SPACE_WEATHER = '0192f2a4-0000-7000-8000-000000000202';
const ASSIGNED = auditFixture({
	id: 9,
	action: 'catalog.assign_schema',
	object_type: 'catalog',
	detail: { schema_id: SPACE_WEATHER, previous: BASE }
});
const CREATED = auditFixture({
	id: 1,
	action: 'catalog.create',
	object_type: 'catalog',
	detail: { name: 'space-weather', schema_id: BASE }
});

function activityEvent(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/space-weather/activity${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/(overview)/activity',
		params: { catalog: 'space-weather' }
	}).event;
}

function stub(routes: Record<string, FetchAnswer>) {
	const api = fakeApi(routes);
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

describe('/catalogs/[catalog]/activity load', () => {
	it('returns a page of entries and names their schemas, each looked up once', async () => {
		const api = stub({
			'/catalogs/space-weather/log?limit=50': jsonResponse(
				pageFixture([ASSIGNED, auditFixture(), CREATED], 'older')
			),
			[`/schemas/${SPACE_WEATHER}`]: jsonResponse(
				schemaFixture({ id: SPACE_WEATHER, name: 'space-weather', version: 1 })
			),
			[`/schemas/${BASE}`]: jsonResponse(schemaFixture())
		});
		expect(await load(activityEvent())).toEqual({
			entries: [ASSIGNED, auditFixture(), CREATED],
			nextCursor: 'older',
			schemas: {
				[SPACE_WEATHER]: { name: 'space-weather', version: 1 },
				[BASE]: { name: 'huron-base', version: 1 }
			}
		});
		expect(api.calls.filter(({ url }) => url.includes('/schemas/'))).toHaveLength(2);
	});

	it('looks the schemas up in parallel', async () => {
		let release = () => {};
		const held = new Promise<void>((resolve) => (release = resolve));
		const api = stub({
			'/catalogs/space-weather/log?limit=50': jsonResponse(pageFixture([ASSIGNED])),
			[`/schemas/${SPACE_WEATHER}`]: async () => {
				await held;
				return jsonResponse(schemaFixture({ id: SPACE_WEATHER, name: 'space-weather' }));
			},
			[`/schemas/${BASE}`]: async () => {
				await held;
				return jsonResponse(schemaFixture());
			}
		});
		const loaded = load(activityEvent());
		await vi.waitFor(() => expect(api.calls).toHaveLength(3));
		release();
		expect(Object.keys((await loaded).schemas)).toHaveLength(2);
	});

	it('leaves a schema the user may not see unnamed without logging it', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		stub({
			'/catalogs/space-weather/log?limit=50': jsonResponse(pageFixture([ASSIGNED])),
			[`/schemas/${SPACE_WEATHER}`]: problemResponse(404, 'NOT_FOUND'),
			[`/schemas/${BASE}`]: jsonResponse(schemaFixture())
		});
		const data = await load(activityEvent());
		expect(data.schemas).toEqual({ [BASE]: { name: 'huron-base', version: 1 } });
		expect(log).not.toHaveBeenCalled();
	});

	it('logs a lookup that failed and still shows the page', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		stub({
			'/catalogs/space-weather/log?limit=50': jsonResponse(pageFixture([CREATED])),
			[`/schemas/${BASE}`]: problemResponse(503, 'DEPENDENCY_UNAVAILABLE')
		});
		const data = await load(activityEvent());
		expect(data.schemas).toEqual({});
		expect(log).toHaveBeenCalledOnce();
	});

	it('pages by the cursor alone and restarts a stale one', async () => {
		stub({
			'/catalogs/space-weather/log?cursor=older&limit=50': jsonResponse(pageFixture([], 'oldest')),
			'/catalogs/space-weather/log?cursor=stale&limit=50': problemResponse(400, 'INVALID_CURSOR')
		});
		expect(await load(activityEvent('?cursor=older'))).toEqual({
			entries: [],
			nextCursor: 'oldest',
			schemas: {}
		});
		const outcome = await load(activityEvent('?cursor=stale')).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/catalogs/space-weather/activity?notice=page_expired'
		);
	});
});
