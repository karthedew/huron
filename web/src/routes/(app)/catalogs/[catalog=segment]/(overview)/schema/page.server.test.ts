// @vitest-environment node
import { isHttpError } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { schemaView } from '$lib/schema-view';
import {
	fakeApi,
	jsonResponse,
	jsonTextResponse,
	problemResponse
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

function schemaEvent() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/catalogs/heliophysics/schema',
		routeId: '/(app)/catalogs/[catalog=segment]/(overview)/schema',
		params: { catalog: 'heliophysics' }
	}).event;
}

describe('/catalogs/[catalog]/schema load', () => {
	it("returns the catalog's resolved schema as its table", async () => {
		const schema = {
			type: 'object',
			required: ['title'],
			properties: { title: { type: 'string' } }
		};
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/catalogs/heliophysics/schema': jsonResponse(schema) }).fetch
		);
		expect(await load(schemaEvent())).toEqual({ schema: schemaView(schema) });
	});

	it('returns page data SvelteKit can send, whatever the properties are named', async () => {
		const schema = {
			type: 'object',
			properties: { ['__proto__']: { type: 'string', title: 'Proto field' } }
		};
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/catalogs/heliophysics/schema': jsonResponse(schema) }).fetch
		);
		const data = await load(schemaEvent());
		expect(() => serializePageData(data)).not.toThrow();
		expect(data.schema.fields.map(({ key, label }) => [key, label])).toEqual([
			['__proto__', 'Proto field']
		]);
		expect(JSON.parse(data.schema.json)).toEqual(schema);
	});

	it('keeps the digits the API wrote for integers too large for a number', async () => {
		const text =
			'{"type":"object","properties":{"epoch":{"type":"integer",' +
			'"minimum":-9223372036854775807,"maximum":9223372036854775807}}}';
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/catalogs/heliophysics/schema': jsonTextResponse(text) }).fetch
		);
		const { schema } = await load(schemaEvent());
		expect(schema.fields.map(({ constraints }) => constraints)).toEqual([
			['from -9223372036854775807 to 9223372036854775807']
		]);
		expect(schema.json).toContain('"maximum": 9223372036854775807');
		expect(schema.json).not.toContain('9223372036854776000');
	});

	it('shows the 503 page during an outage', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/catalogs/heliophysics/schema': problemResponse(503, 'API_UNREACHABLE') }).fetch
		);
		const outcome = await load(schemaEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 503)).toBe(true);
	});
});
