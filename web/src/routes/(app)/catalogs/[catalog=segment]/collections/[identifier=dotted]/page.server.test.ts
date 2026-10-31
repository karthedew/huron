// @vitest-environment node
import { isHttpError } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { metadataView } from '$lib/metadata';
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
import { huronBase, spaceWeather } from '$lib/testing/schemas';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { load as layoutLoad } from './+layout.server';
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
const MAG = collectionFixture({
	metadata: {
		title: 'ACE MAG level 2, 2024',
		description: 'Vectors.',
		contacts: [{ name: 'ACE MAG team', email: 'ace-mag@example.org' }],
		start_time: '2024-01-01T00:00:00Z',
		labels: { mission: 'ace' }
	}
});
const FLARES = collectionFixture({
	id: '0192f2a4-0000-7000-8000-000000000402',
	identifier: 'space-weather.alerts.flare-list-2024',
	catalog: 'space-weather',
	namespace: 'alerts',
	name: 'flare-list-2024',
	state: 'incomplete',
	metadata: {
		title: 'Flare list 2024',
		description: 'Flares.',
		contacts: [{ name: 'n', email: 'x' }]
	},
	problems: [
		{ path: '/', message: "'mission' is a required property", rule: 'required' },
		{ path: '/contacts/0/email', message: "'x' is not a 'email'", rule: 'format' }
	]
});

const COLLECTION = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024';

function overviewEvent(catalog = 'heliophysics', identifier = 'solar-wind.ace.mag-l2-2024') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/${catalog}/collections/${identifier}`,
		routeId: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]',
		params: { catalog, identifier }
	}).event;
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	const api = fakeApi({
		[COLLECTION]: jsonResponse(MAG),
		[`/collections/${ID}/schema`]: jsonResponse(huronBase()),
		...overrides
	});
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

describe('/catalogs/[catalog]/collections/[identifier] load', () => {
	it('returns the metadata against the resolved schema', async () => {
		const api = routes();
		expect(await load(overviewEvent())).toEqual({
			metadata: metadataView(MAG.metadata, huronBase()),
			problems: { rows: [], more: 0 },
			schemaResolved: true
		});
		expect(api.calls.map(({ url }) => new URL(url).pathname)).toEqual([
			`/api/v1${COLLECTION}`,
			`/api/v1/collections/${ID}/schema`
		]);
	});

	it('names the field of each problem of an incomplete collection', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/catalogs/space-weather/collections/alerts.flare-list-2024': jsonResponse(FLARES),
				[`/collections/${FLARES.id}/schema`]: jsonResponse(spaceWeather())
			}).fetch
		);
		const data = await load(overviewEvent('space-weather', 'alerts.flare-list-2024'));
		expect(data.problems).toEqual({
			rows: [
				{ field: null, message: "'mission' is a required property" },
				{ field: 'Contacts › 1 › Email', message: "'x' is not a 'email'" }
			],
			more: 0
		});
		expect(data.metadata.fields.find(({ key }) => key === 'mission')?.value).toEqual({
			kind: 'missing'
		});
	});

	it("shows the fields by their keys when the collection's override no longer fits", async () => {
		routes({
			[`/collections/${ID}/schema`]: problemResponse(422, 'SCHEMA_INCOMPATIBLE')
		});
		const data = await load(overviewEvent());
		expect(data.schemaResolved).toBe(false);
		expect(data.metadata).toEqual(metadataView(MAG.metadata, null));
	});

	it('shows the 503 page when the schema cannot be read for another reason', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		routes({ [`/collections/${ID}/schema`]: problemResponse(503, 'DEPENDENCY_UNAVAILABLE') });
		const outcome = await load(overviewEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 503)).toBe(true);
	});

	it('shows a collection that does not exist as not found, without reading a schema', async () => {
		const api = routes({ [COLLECTION]: problemResponse(404, 'NOT_FOUND') });
		const outcome = await load(overviewEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
		expect(api.calls).toHaveLength(1);
	});

	it('returns page data SvelteKit can send, whatever keys the metadata and schema hold', async () => {
		const proto = collectionFixture({
			state: 'draft',
			metadata: parsedObject(
				'{"title":"Proto","__proto__":{"x":1},"labels":{"__proto__":"x"},"list":[{"__proto__":2}]}'
			),
			problems: [{ path: '/__proto__/x', message: 'bad', rule: 'type' }]
		});
		routes({
			[COLLECTION]: jsonResponse(proto),
			[`/collections/${ID}/schema`]: jsonResponse(
				parsedObject(
					'{"type":"object","required":["__proto__"],"properties":{"__proto__":{"type":"object","title":"Proto"}}}'
				)
			)
		});
		const data = await load(overviewEvent());
		expect(() => serializePageData(data)).not.toThrow();
		expect(data.problems).toEqual({ rows: [{ field: 'Proto › X', message: 'bad' }], more: 0 });
	});

	it('shares the read of the collection with the layout', async () => {
		const ace = namespaceFixture({ name: 'ace', path: 'solar-wind.ace', parent: 'solar-wind' });
		const api = routes({
			'/catalogs/heliophysics/namespaces?parent=solar-wind&limit=50': jsonResponse(
				pageFixture([ace])
			),
			'/catalogs/heliophysics/namespaces/solar-wind/collections?limit=50': jsonResponse(
				pageFixture([])
			),
			'/catalogs/heliophysics/namespaces?parent=solar-wind.ace&limit=50': jsonResponse(
				pageFixture([])
			),
			'/catalogs/heliophysics/namespaces/solar-wind.ace/collections?limit=50': jsonResponse(
				pageFixture([MAG])
			)
		});
		const event = overviewEvent();
		await Promise.all([layoutLoad(event), load(event)]);
		expect(api.calls.filter(({ url }) => url.endsWith(COLLECTION))).toHaveLength(1);
	});
});
