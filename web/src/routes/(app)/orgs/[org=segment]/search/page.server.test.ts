// @vitest-environment node
import { isHttpError } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Catalog, RoleGrant } from '$api/types';
import { emptySearch, searchResult } from '$lib/search';
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
import { parsedObject } from '$lib/testing/json';
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
const HELIOPHYSICS = catalogFixture();
const SPACE_WEATHER = catalogFixture({
	id: '0192f2a4-0000-7000-8000-000000000102',
	name: 'space-weather',
	display_name: 'Space Weather'
});
const MAG = collectionFixture({
	id: 'c-mag',
	metadata: { title: 'ACE MAG level 2, 2024', labels: { mission: 'ace' } }
});

const CATALOGS = '/catalogs?organization=helio&limit=50';

function searchEvent(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/orgs/helio/search${query}`,
		routeId: '/(app)/orgs/[org=segment]/search',
		params: { org: 'helio' }
	});
}

/** The API of an organization with these catalogs, for a user with these roles. */
function organization(
	catalogs: Catalog[],
	roles: RoleGrant[] = [],
	routes: Record<string, FetchAnswer> = {}
) {
	const fake = fakeApi({
		[CATALOGS]: jsonResponse(pageFixture(catalogs)),
		'/auth/whoami': jsonResponse(whoamiFixture({ roles })),
		'/organizations?limit=500': jsonResponse(pageFixture([HELIO])),
		...routes
	});
	vi.stubGlobal('fetch', fake.fetch);
	return fake;
}

/** The searches among the API calls made. */
function searches(calls: ReadonlyArray<{ url: string }>): string[] {
	return calls.map(({ url }) => url).filter((url) => url.includes('/search?'));
}

describe('/orgs/[org]/search load', () => {
	it("searches each catalog for the address's search and returns plain rows", async () => {
		const fake = organization([HELIOPHYSICS, SPACE_WEATHER], [], {
			'/catalogs/heliophysics/search?q=ace&limit=5': jsonResponse(pageFixture([MAG], 'more')),
			'/catalogs/space-weather/search?q=ace&limit=5': jsonResponse(pageFixture([]))
		});
		const search = { ...emptySearch(), q: 'ace' };
		expect(await load(searchEvent('?q=ace').event)).toEqual({
			search,
			errors: { q: null, label: null, form: null },
			pendingLabel: '',
			drafts: false,
			catalogCount: 2,
			truncated: false,
			results: {
				exact: null,
				answers: [
					{
						name: 'heliophysics',
						displayName: 'Heliophysics',
						search,
						status: 'answered',
						results: [searchResult(MAG)],
						more: true
					},
					{
						name: 'space-weather',
						displayName: 'Space Weather',
						search,
						status: 'answered',
						results: [],
						more: false
					}
				],
				late: [],
				skipped: []
			}
		});
		expect(searches(fake.calls)).toHaveLength(2);
	});

	it.each([
		['a text longer than the API takes', `?q=${'w'.repeat(201)}`, 'q'],
		['a label without a value', '?q=wind&label=mission', 'label'],
		[
			'more label filters than a search may have',
			`?${Array.from({ length: 11 }, (_, index) => `label=k${index}%3Dv`).join('&')}`,
			'label'
		]
	])('checks the search once and sends none for %s', async (_, query, field) => {
		const fake = organization([HELIOPHYSICS, SPACE_WEATHER]);
		const data = await load(searchEvent(query).event);
		expect(data.errors[field === 'q' ? 'q' : 'label']).not.toBeNull();
		expect(data.results).toBeNull();
		expect(searches(fake.calls)).toEqual([]);
	});

	it('gives a label it cannot read back for its field', async () => {
		organization([HELIOPHYSICS]);
		const data = await load(searchEvent('?q=wind&label=mission').event);
		expect(data.pendingLabel).toBe('mission');
		expect(data.search.q).toBe('wind');
	});

	it('sends nothing for the empty search, which has no results of its own', async () => {
		const fake = organization([HELIOPHYSICS, SPACE_WEATHER]);
		const data = await load(searchEvent().event);
		expect(data.results).toBeNull();
		expect(data.catalogCount).toBe(2);
		expect(searches(fake.calls)).toEqual([]);
	});

	it('finds nothing without asking for labels that give a key two values', async () => {
		const fake = organization([HELIOPHYSICS]);
		const data = await load(searchEvent('?label=mission%3Dace&label=mission%3Dwind').event);
		expect(data.results).toEqual({ exact: null, answers: [], late: [], skipped: [] });
		expect(searches(fake.calls)).toEqual([]);
	});

	it('searches only the first catalogs, and says that there are more', async () => {
		const catalogs = Array.from({ length: 50 }, (_, index) =>
			catalogFixture({ id: `catalog-${index}`, name: `c${String(index).padStart(2, '0')}` })
		);
		organization([], [], {
			[CATALOGS]: jsonResponse(pageFixture(catalogs, 'more'))
		});
		const data = await load(searchEvent().event);
		expect(data.catalogCount).toBe(50);
		expect(data.truncated).toBe(true);
	});

	it('has nothing to search in an organization without catalogs the user can see', async () => {
		const fake = organization([]);
		const data = await load(searchEvent('?q=wind').event);
		expect(data.catalogCount).toBe(0);
		expect(data.results).toBeNull();
		expect(searches(fake.calls)).toEqual([]);
	});

	it('offers drafts where the user may create collections in one of the catalogs', async () => {
		organization([HELIOPHYSICS, SPACE_WEATHER]);
		expect((await load(searchEvent().event)).drafts).toBe(false);
		vi.unstubAllGlobals();
		organization(
			[HELIOPHYSICS, SPACE_WEATHER],
			[{ scope: 'catalog', scope_id: SPACE_WEATHER.id, role: 'contributor' }]
		);
		expect((await load(searchEvent().event)).drafts).toBe(true);
	});

	it('reads draft from the address only where the form offers it', async () => {
		const fake = organization([HELIOPHYSICS], [], {
			'/catalogs/heliophysics/search?q=ace&limit=5': jsonResponse(pageFixture([]))
		});
		const data = await load(searchEvent('?q=ace&state=draft').event);
		expect(data.search.states).toBeNull();
		expect(searches(fake.calls)).toEqual([
			'http://127.0.0.1:8197/api/v1/catalogs/heliophysics/search?q=ace&limit=5'
		]);
	});

	it('has no pages: a cursor in the address is ignored', async () => {
		const fake = organization([HELIOPHYSICS], [], {
			'/catalogs/heliophysics/search?q=ace&limit=5': jsonResponse(pageFixture([]))
		});
		const data = await load(searchEvent('?q=ace&cursor=c2').event);
		expect(data.search.cursor).toBeNull();
		expect(searches(fake.calls)).toHaveLength(1);
	});

	it('shows a refusal of the API at the form, without results', async () => {
		organization([HELIOPHYSICS], [], {
			'/catalogs/heliophysics/search?q=ace&limit=5': problemResponse(422, 'REQUEST_INVALID', {
				problems: [{ path: '/query/q' }]
			})
		});
		const data = await load(searchEvent('?q=ace').event);
		expect(data.errors.q).toBe("The Huron service didn't accept this text.");
		expect(data.results).toBeNull();
	});

	it('conceals an organization the user cannot see as not found', async () => {
		const fake = fakeApi({
			'/catalogs?organization=astro&limit=50': problemResponse(404, 'NOT_FOUND'),
			'/auth/whoami': jsonResponse(whoamiFixture()),
			'/organizations?limit=500': jsonResponse(pageFixture([HELIO]))
		});
		vi.stubGlobal('fetch', fake.fetch);
		const { event } = signedInLoadEvent({
			url: 'http://localhost:4173/orgs/astro/search?q=wind',
			routeId: '/(app)/orgs/[org=segment]/search',
			params: { org: 'astro' }
		});
		const outcome = await load(event).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome) && outcome.status).toBe(404);
		expect(searches(fake.calls)).toEqual([]);
	});

	it('returns page data SvelteKit can send, whatever keys labels use', async () => {
		const hostile = collectionFixture({
			metadata: parsedObject('{"title":"T","labels":{"__proto__":"x","mission":"ace"}}')
		});
		organization([HELIOPHYSICS], [], {
			'/catalogs/heliophysics/search?q=ace&limit=5': jsonResponse(pageFixture([hostile]))
		});
		const data = await load(searchEvent('?q=ace').event);
		expect(() => serializePageData(data)).not.toThrow();
	});
});
