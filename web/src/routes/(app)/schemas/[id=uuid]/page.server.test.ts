// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { schemaView } from '$lib/schema-view';
import {
	fakeApi,
	jsonResponse,
	jsonTextResponse,
	organizationFixture,
	pageFixture,
	problemResponse,
	schemaFixture
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

const ID = schemaFixture().id;
const PARENT = '0192f2a4-0000-7000-8000-000000000202';
function event(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/schemas/${ID}${query}`,
		routeId: '/(app)/schemas/[id=uuid]',
		params: { id: ID }
	}).event;
}
const ORGANIZATIONS = {
	'/organizations?limit=500': jsonResponse(pageFixture([organizationFixture()]))
};

describe('/schemas/[id] load', () => {
	it('uses the linked source beyond the bounded organization list after checking ownership', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/organizations?limit=500': jsonResponse(pageFixture([], 'next')),
				'/organizations/helio': jsonResponse(organizationFixture()),
				[`/schemas/${ID}`]: jsonResponse(
					schemaFixture({ organization_id: organizationFixture().id })
				),
				[`/schemas/${ID}/resolved`]: jsonResponse({})
			}).fetch
		);
		expect(await load(event('?organization=helio'))).toMatchObject({
			schemaOrganization: { name: 'helio' },
			organization: 'helio'
		});
	});

	it('rejects a linked source that does not own the schema', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				[`/schemas/${ID}`]: jsonResponse(schemaFixture({ organization_id: 'other-organization' })),
				[`/schemas/${ID}/resolved`]: jsonResponse({})
			}).fetch
		);
		const outcome = await load(event('?organization=helio')).catch((failure: unknown) => failure);
		expect(isHttpError(outcome, 400)).toBe(true);
	});

	it('validates a linked source before reading any schema', async () => {
		const fake = fakeApi({});
		vi.stubGlobal('fetch', fake.fetch);
		const outcome = await load(event('?organization=bad%2Fscope')).catch(
			(failure: unknown) => failure
		);
		expect(isHttpError(outcome, 400)).toBe(true);
		expect(fake.calls).toHaveLength(0);
	});

	it('names a visible organization version and its parent and composes both document views', async () => {
		const document = { properties: { mission: { type: 'string' } } };
		const resolved = { properties: { title: { type: 'string' }, mission: { type: 'string' } } };
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				[`/schemas/${ID}`]: jsonResponse(
					schemaFixture({
						name: 'space-weather',
						organization_id: organizationFixture().id,
						extends_id: PARENT,
						document
					})
				),
				[`/schemas/${ID}/resolved`]: jsonResponse(resolved),
				[`/schemas/${PARENT}`]: jsonResponse(schemaFixture({ id: PARENT }))
			}).fetch
		);
		const data = await load(event());
		expect(data).toMatchObject({
			organization: 'helio',
			schemaOrganization: { name: 'helio' },
			entry: { name: 'space-weather' },
			parentSchema: { id: PARENT, name: 'huron-base' }
		});
		expect(data.resolvedSchema).toEqual(schemaView(resolved));
		expect(data.authoredSchema).toEqual(schemaView(document));
	});

	it('keeps authored and resolved schema keys safe for devalue and large integers exact', async () => {
		const document =
			'{"properties":{"__proto__":{"type":"integer","maximum":9223372036854775807}}}';
		const entry = JSON.stringify(schemaFixture({ document: {} })).replace(
			'"document":{}',
			`"document":${document}`
		);
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				[`/schemas/${ID}`]: jsonTextResponse(entry),
				[`/schemas/${ID}/resolved`]: jsonTextResponse(document)
			}).fetch
		);
		const data = await load(event());
		expect(() => serializePageData(data)).not.toThrow();
		for (const view of [data.resolvedSchema, data.authoredSchema]) {
			expect(view.fields[0]).toMatchObject({
				key: '__proto__',
				constraints: ['at most 9223372036854775807']
			});
			expect(view.json).toContain('9223372036854775807');
		}
		expect(data.parentSchema).toBeNull();
		expect(data.schemaOrganization).toBeNull();
	});

	it('allows an empty document and an owner outside the shell organization list', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/organizations?limit=500': jsonResponse(pageFixture([])),
				[`/schemas/${ID}`]: jsonResponse(
					schemaFixture({ organization_id: 'not-listed', document: {} })
				),
				[`/schemas/${ID}/resolved`]: jsonResponse({})
			}).fetch
		);
		expect(await load(event())).toMatchObject({
			schemaOrganization: null,
			resolvedSchema: { fields: [] },
			authoredSchema: { fields: [] }
		});
	});

	it.each([404, 403, 503])('turns a %i read into the fixed error page', async (status) => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				[`/schemas/${ID}`]: problemResponse(status, 'FAILURE', {}, 'private API text'),
				[`/schemas/${ID}/resolved`]: jsonResponse({})
			}).fetch
		);
		const outcome = await load(event()).catch((failure: unknown) => failure);
		expect(isHttpError(outcome, status)).toBe(true);
		expect(JSON.stringify(outcome)).not.toContain('private API text');
	});

	it('ends the session when an exact registry read rejects the token', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				[`/schemas/${ID}`]: problemResponse(401, 'UNAUTHENTICATED'),
				[`/schemas/${ID}/resolved`]: jsonResponse({})
			}).fetch
		);
		const request = event();
		const outcome = await load(request).catch((failure: unknown) => failure);
		expect(isRedirect(outcome)).toBe(true);
		expect(request.cookies.get('huron_session')).toBeUndefined();
	});
});
