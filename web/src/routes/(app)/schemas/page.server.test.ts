// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	fakeApi,
	jsonResponse,
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

function event(query = '?organization=helio', remembered?: string) {
	return signedInLoadEvent({
		url: `http://localhost:4173/schemas${query}`,
		routeId: '/(app)/schemas',
		params: {},
		cookies: remembered === undefined ? {} : { huron_org: remembered }
	}).event;
}

const ORGANIZATIONS = {
	'/organizations?limit=500': jsonResponse(pageFixture([organizationFixture()]))
};

describe('/schemas load', () => {
	it.each([
		['helio', 'helio'],
		['hidden', ''],
		[undefined, '']
	])('makes the default scope explicit with remembered %s', async (remembered, selected) => {
		const fake = fakeApi(ORGANIZATIONS);
		vi.stubGlobal('fetch', fake.fetch);
		const outcome = await load(event('', remembered)).catch((failure: unknown) => failure);
		expect(isRedirect(outcome)).toBe(true);
		expect(outcome).toMatchObject({ status: 303, location: `/schemas?organization=${selected}` });
		expect(fake.calls).toHaveLength(1);
	});

	it('lists one page of organization versions and removes authored documents', async () => {
		const entry = schemaFixture({
			organization_id: organizationFixture().id,
			document: { ['__proto__']: { type: 'string' } }
		});
		const fake = fakeApi({
			...ORGANIZATIONS,
			'/organizations/helio': jsonResponse(organizationFixture()),
			'/organizations/helio/schemas?cursor=page2&limit=50': jsonResponse(
				pageFixture([entry], 'page3')
			)
		});
		vi.stubGlobal('fetch', fake.fetch);
		const data = await load(event('?organization=helio&cursor=page2'));
		expect(data).toMatchObject({
			organization: 'helio',
			schemaOrganization: { name: 'helio' },
			schemas: [{ id: entry.id }],
			nextCursor: 'page3'
		});
		expect(data.schemas[0]).not.toHaveProperty('document');
		expect(() => serializePageData(data)).not.toThrow();
		expect(fake.calls.every(({ init }) => init?.method === 'GET')).toBe(true);
	});

	it('lists platform versions without needing membership in an organization', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/organizations?limit=500': jsonResponse(pageFixture([])),
				'/platform/schemas?limit=50': jsonResponse(pageFixture([schemaFixture()]))
			}).fetch
		);
		expect(await load(event('?organization='))).toMatchObject({
			schemaOrganization: null,
			organizationChoices: [],
			schemas: [{ name: 'huron-base' }]
		});
	});

	it('keeps an empty registry distinct from a failed read', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				'/organizations/helio': jsonResponse(organizationFixture()),
				'/organizations/helio/schemas?limit=50': jsonResponse(pageFixture([]))
			}).fetch
		);
		expect(await load(event())).toMatchObject({ schemas: [], nextCursor: null });
	});

	it('includes a selected organization beyond the first page of source choices', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/organizations?limit=500': jsonResponse(pageFixture([], 'more')),
				'/organizations/helio': jsonResponse(organizationFixture()),
				'/organizations/helio/schemas?limit=50': jsonResponse(pageFixture([]))
			}).fetch
		);
		expect(await load(event())).toMatchObject({
			organizationChoices: [{ name: 'helio' }],
			moreOrganizations: true
		});
	});

	it.each(['../platform', 'helio/schemas', 'x'.repeat(64)])(
		'refuses invalid organization %s before any read',
		async (name) => {
			const fake = fakeApi({});
			vi.stubGlobal('fetch', fake.fetch);
			const outcome = await load(event(`?organization=${encodeURIComponent(name)}`)).catch(
				(failure: unknown) => failure
			);
			expect(isHttpError(outcome, 400)).toBe(true);
			expect(fake.calls).toHaveLength(0);
		}
	);

	it('does not list schemas when the organization is hidden or missing', async () => {
		const fake = fakeApi({
			...ORGANIZATIONS,
			'/organizations/helio': problemResponse(404, 'NOT_FOUND')
		});
		vi.stubGlobal('fetch', fake.fetch);
		const outcome = await load(event()).catch((failure: unknown) => failure);
		expect(isHttpError(outcome, 404)).toBe(true);
		expect(fake.calls).toHaveLength(2);
	});

	it('returns to the same scope when a cursor expires', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				'/organizations/helio': jsonResponse(organizationFixture()),
				'/organizations/helio/schemas?cursor=old&limit=50': problemResponse(400, 'INVALID_CURSOR')
			}).fetch
		);
		const outcome = await load(event('?organization=helio&cursor=old')).catch(
			(failure: unknown) => failure
		);
		expect(outcome).toMatchObject({
			status: 303,
			location: '/schemas?organization=helio&notice=page_expired'
		});
	});

	it.each([403, 503])('uses the fixed error page for a %i registry failure', async (status) => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				'/organizations/helio': jsonResponse(organizationFixture()),
				'/organizations/helio/schemas?limit=50': problemResponse(
					status,
					'FAILURE',
					{},
					'private API text'
				)
			}).fetch
		);
		const outcome = await load(event()).catch((failure: unknown) => failure);
		expect(isHttpError(outcome, status)).toBe(true);
		expect(JSON.stringify(outcome)).not.toContain('private API text');
	});

	it('ends the web session when the registry rejects the token', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				...ORGANIZATIONS,
				'/organizations/helio': jsonResponse(organizationFixture()),
				'/organizations/helio/schemas?limit=50': problemResponse(401, 'UNAUTHENTICATED')
			}).fetch
		);
		const request = event();
		const outcome = await load(request).catch((failure: unknown) => failure);
		expect(isRedirect(outcome)).toBe(true);
		expect(outcome).toMatchObject({
			status: 303,
			location: expect.stringContaining('status=expired')
		});
		expect(request.cookies.get('huron_session')).toBeUndefined();
	});
});
