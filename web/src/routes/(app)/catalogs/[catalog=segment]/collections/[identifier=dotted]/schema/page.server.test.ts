// @vitest-environment node
import { isHttpError } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { schemaView } from '$lib/schema-view';
import {
	collectionFixture,
	fakeApi,
	jsonResponse,
	jsonTextResponse,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { parsedObject } from '$lib/testing/json';
import { serializePageData } from '$lib/testing/page-data';
import { huronBase } from '$lib/testing/schemas';
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
const COLLECTION = '/catalogs/heliophysics/collections/solar-wind.wind.swe-2023';
const OVERRIDE = {
	type: 'object',
	properties: { release_date: { type: 'string', format: 'date', title: 'Release date' } },
	required: ['release_date']
};

function schemaEvent() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/catalogs/heliophysics/collections/solar-wind.wind.swe-2023/schema',
		routeId: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/schema',
		params: { catalog: 'heliophysics', identifier: 'solar-wind.wind.swe-2023' }
	}).event;
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	const api = fakeApi({
		[COLLECTION]: jsonResponse(collectionFixture({ schema_override: OVERRIDE })),
		[`/collections/${ID}/schema`]: jsonResponse(huronBase()),
		...overrides
	});
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

describe('/catalogs/[catalog]/collections/[identifier]/schema load', () => {
	it('returns the resolved schema and the override alone, each as its table', async () => {
		routes();
		expect(await load(schemaEvent())).toEqual({
			schema: { ...schemaView(huronBase()), title: null, description: null },
			override: schemaView(OVERRIDE)
		});
	});

	it('introduces the composed table by neither document’s words beside an override', async () => {
		// As the API composes them: the override's title, and huron-base's description.
		const override = { ...OVERRIDE, title: 'Wind SWE additions' };
		const composed = { ...huronBase(), title: 'Wind SWE additions' };
		routes({
			[COLLECTION]: jsonResponse(collectionFixture({ schema_override: override })),
			[`/collections/${ID}/schema`]: jsonResponse(composed)
		});
		const { schema, override: own } = await load(schemaEvent());
		expect(schema).toMatchObject({ title: null, description: null });
		expect(schema?.fields).toEqual(schemaView(composed).fields);
		expect(schema?.json).toBe(schemaView(composed).json);
		expect(own).toMatchObject({ title: 'Wind SWE additions', description: null });
	});

	it('has no override table for a collection without one', async () => {
		routes({ [COLLECTION]: jsonResponse(collectionFixture()) });
		const data = await load(schemaEvent());
		expect(data.override).toBeNull();
		expect(data.schema).toEqual(schemaView(huronBase()));
		expect(data.schema?.title).toBe('Huron base metadata');
	});

	it('still shows the override when it no longer fits the catalog’s schema', async () => {
		routes({ [`/collections/${ID}/schema`]: problemResponse(422, 'SCHEMA_INCOMPATIBLE') });
		expect(await load(schemaEvent())).toEqual({ schema: null, override: schemaView(OVERRIDE) });
	});

	it('shows the 400 page for any other refusal of the schema', async () => {
		routes({ [`/collections/${ID}/schema`]: problemResponse(422, 'VALIDATION') });
		const outcome = await load(schemaEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 400)).toBe(true);
	});

	it('keeps the digits the API wrote for integers too large for a number', async () => {
		const override =
			'{"type":"object","properties":{"epoch":{"type":"integer","title":"First epoch (TT2000)",' +
			'"minimum":-9223372036854775807,"maximum":9223372036854775807}}}';
		const answer = JSON.stringify(collectionFixture());
		expect(answer).toContain('"schema_override":null');
		const exact = answer.replace('"schema_override":null', `"schema_override":${override}`);
		const api = routes({
			[COLLECTION]: jsonTextResponse(exact),
			[`/collections/${ID}`]: jsonTextResponse(exact),
			[`/collections/${ID}/schema`]: jsonTextResponse(override)
		});
		const data = await load(schemaEvent());
		for (const view of [data.schema, data.override]) {
			expect(view?.fields.map(({ constraints }) => constraints)).toEqual([
				['from -9223372036854775807 to 9223372036854775807']
			]);
			expect(view?.json).toContain('"maximum": 9223372036854775807');
		}
		expect(() => serializePageData(data)).not.toThrow();
		// The collection is parsed plainly, as every page reads it; only its override is read again.
		expect(api.calls.filter(({ url }) => url.endsWith(`/collections/${ID}`))).toHaveLength(1);
	});

	it('reads the collection only once where its override holds no integer a parse rounds', async () => {
		const api = routes();
		await load(schemaEvent());
		expect(api.calls.map(({ url }) => new URL(url).pathname)).toEqual([
			'/api/v1/catalogs/heliophysics/collections/solar-wind.wind.swe-2023',
			`/api/v1/collections/${ID}/schema`
		]);
	});

	it('returns page data SvelteKit can send, whatever the schemas name', async () => {
		const proto = parsedObject(
			'{"type":"object","properties":{"__proto__":{"type":"string","title":"Proto"}}}'
		);
		routes({
			[COLLECTION]: jsonResponse(collectionFixture({ schema_override: proto })),
			[`/collections/${ID}/schema`]: jsonResponse(proto)
		});
		const data = await load(schemaEvent());
		expect(() => serializePageData(data)).not.toThrow();
		expect(data.override?.fields.map(({ key, label }) => [key, label])).toEqual([
			['__proto__', 'Proto']
		]);
	});
});
