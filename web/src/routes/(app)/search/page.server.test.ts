// @vitest-environment node
import { isHttpError } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { emptySearch } from '$lib/search';
import {
	catalogFixture,
	collectionFixture,
	fakeApi,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse,
	whoamiFixture,
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
const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });
const CATALOG = catalogFixture();
function event(query = '', cookies: Record<string, string> = {}) {
	return signedInLoadEvent({
		url: `http://localhost:4173/search${query}`,
		routeId: '/(app)/search',
		params: {},
		cookies
	}).event;
}
function stub(routes: Record<string, FetchAnswer> = {}) {
	const fake = fakeApi({
		'/organizations?limit=500': jsonResponse(pageFixture([HELIO, GEO])),
		'/auth/whoami': jsonResponse(whoamiFixture()),
		'/catalogs?organization=helio&limit=50': jsonResponse(pageFixture([CATALOG])),
		'/catalogs?organization=geo&limit=50': jsonResponse(pageFixture([])),
		'/catalogs/heliophysics': jsonResponse(CATALOG),
		...routes
	});
	vi.stubGlobal('fetch', fake.fetch);
	return fake;
}

describe('the central Search load', () => {
	it('offers scope selectors without searching every catalog until filters are supplied', async () => {
		const fake = stub();
		const data = await load(event());
		expect(data.organization).toBe('helio');
		expect(data.scope).toEqual({
			organization: 'helio',
			catalog: null,
			catalogs: [{ name: 'heliophysics', display_name: 'Heliophysics' }]
		});
		expect(data.organizationSearch?.results).toBeNull();
		expect(fake.calls.some(({ url }) => url.includes('/search?'))).toBe(false);
		expect(() => serializePageData(data)).not.toThrow();
	});
	it('keeps the remembered organization when no explicit scope was selected', async () => {
		stub();
		expect((await load(event('', { huron_org: 'geo' }))).organization).toBe('geo');
	});
	it('searches all visible catalogs within a selected organization using the bounded fan-out', async () => {
		stub({
			'/catalogs/heliophysics/search?q=wind&limit=5': jsonResponse(
				pageFixture([collectionFixture()], 'more')
			)
		});
		const data = await load(event('?organization=helio&q=wind'));
		expect(data.organizationSearch?.results?.answers[0]).toMatchObject({
			status: 'answered',
			more: true
		});
		expect(data.catalogSearch).toBeNull();
	});
	it('infers a selected catalog’s organization and returns its paged results', async () => {
		stub({
			'/catalogs/heliophysics/search?q=wind&cursor=c2&limit=25': jsonResponse(
				pageFixture([collectionFixture()], 'c3')
			)
		});
		const data = await load(event('?catalog=heliophysics&q=wind&cursor=c2', { huron_org: 'geo' }));
		expect(data.organization).toBe('helio');
		expect(data.catalogSearch?.nextCursor).toBe('c3');
		expect(data.organizationSearch).toBeNull();
		expect(() => serializePageData(data)).not.toThrow();
	});
	it('lists a selected catalog even when it falls after the catalog choice bound', async () => {
		stub({
			'/catalogs?organization=helio&limit=50': jsonResponse(pageFixture([])),
			'/catalogs/heliophysics/search?limit=25': jsonResponse(pageFixture([]))
		});
		expect((await load(event('?catalog=heliophysics'))).scope?.catalogs).toHaveLength(1);
	});
	it('includes an explicitly selected organization beyond the listed first page', async () => {
		stub({
			'/organizations?limit=500': jsonResponse(pageFixture([HELIO], 'next')),
			'/organizations/geo': jsonResponse(GEO)
		});
		const data = await load(event('?organization=geo'));
		expect(data.moreOrganizations).toBe(true);
		expect(data.organizationList.map(({ name }) => name)).toEqual(['helio', 'geo']);
		expect(data.selectedOrganization?.name).toBe('geo');
	});
	it('leaves invalid text and labels in the form and sends no search request', async () => {
		const fake = stub();
		const data = await load(event(`?q=${'w'.repeat(201)}&label=mission`));
		expect(data.organizationSearch?.errors.q).toContain('at most 200');
		expect(data.organizationSearch?.errors.label).toContain('key=value');
		expect(fake.calls.some(({ url }) => url.includes('/search?'))).toBe(false);
	});
	it('rejects invalid scope selectors before reading the API', async () => {
		const fake = stub();
		const outcome = await load(event('?catalog=../other')).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome) && outcome.status).toBe(400);
		expect(fake.calls).toHaveLength(0);
	});
	it('rejects a catalog from a different explicitly selected organization', async () => {
		stub();
		const outcome = await load(event('?organization=geo&catalog=heliophysics')).catch(
			(thrown: unknown) => thrown
		);
		expect(isHttpError(outcome) && outcome.status).toBe(400);
	});
	it('handles accounts with no visible organizations', async () => {
		stub({ '/organizations?limit=500': jsonResponse(pageFixture([])) });
		const data = await load(event());
		expect(data.selectedOrganization).toBeNull();
		expect(data.search).toEqual(emptySearch());
	});
	it('conceals an inaccessible selected organization as not found', async () => {
		stub({ '/organizations/hidden': problemResponse(404, 'NOT_FOUND') });
		const outcome = await load(event('?organization=hidden')).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome) && outcome.status).toBe(404);
	});
});
