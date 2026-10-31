// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	catalogFixture,
	fakeApi,
	jsonResponse,
	namespaceFixture,
	pageFixture,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { sessionStore } from '$lib/server/sessions';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { load } from './+layout.server';

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

const HELIOPHYSICS = catalogFixture();
const SPACE_WEATHER = catalogFixture({
	id: '0192f2a4-0000-7000-8000-000000000102',
	name: 'space-weather',
	display_name: 'Space Weather'
});
const SOLAR_WIND = namespaceFixture();

function catalogEvent(catalog = 'heliophysics') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/${catalog}`,
		routeId: '/(app)/catalogs/[catalog=segment]',
		params: { catalog }
	});
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	return fakeApi({
		'/catalogs/heliophysics': jsonResponse(HELIOPHYSICS),
		'/catalogs?organization=helio&limit=100': jsonResponse(
			pageFixture([HELIOPHYSICS, SPACE_WEATHER])
		),
		'/catalogs/heliophysics/namespaces?limit=50': jsonResponse(pageFixture([SOLAR_WIND])),
		...overrides
	});
}

describe('/catalogs/[catalog] layout load', () => {
	it("returns the catalog, its organization's catalogs and the explorer's root", async () => {
		vi.stubGlobal('fetch', routes().fetch);
		expect(await load(catalogEvent().event)).toEqual({
			organization: 'helio',
			catalog: HELIOPHYSICS,
			catalogs: [
				{ name: 'heliophysics', display_name: 'Heliophysics' },
				{ name: 'space-weather', display_name: 'Space Weather' }
			],
			moreCatalogs: false,
			root: {
				parent: '',
				namespaces: [{ name: 'solar-wind', path: 'solar-wind', empty: false }],
				namespacesNext: null,
				collections: [],
				collectionsNext: null
			}
		});
	});

	it('reads the catalog and the root together, and the catalogs once the organization is known', async () => {
		let release = () => {};
		const held = new Promise<void>((resolve) => (release = resolve));
		const api = routes({
			'/catalogs/heliophysics': async () => {
				await held;
				return jsonResponse(HELIOPHYSICS);
			}
		});
		vi.stubGlobal('fetch', api.fetch);
		const loaded = load(catalogEvent().event);
		await vi.waitFor(() => expect(api.calls).toHaveLength(2));
		expect(api.calls.map(({ url }) => new URL(url).pathname)).toEqual([
			'/api/v1/catalogs/heliophysics',
			'/api/v1/catalogs/heliophysics/namespaces'
		]);
		release();
		await loaded;
		expect(api.calls).toHaveLength(3);
	});

	it('says when the organization has more catalogs than the explorer lists', async () => {
		vi.stubGlobal(
			'fetch',
			routes({
				'/catalogs?organization=helio&limit=100': jsonResponse(pageFixture([HELIOPHYSICS], 'c2'))
			}).fetch
		);
		const data = await load(catalogEvent().event);
		expect(data.moreCatalogs).toBe(true);
	});

	it('conceals a catalog the user cannot see as not found', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/catalogs/exoplanets': problemResponse(404, 'NOT_FOUND'),
				'/catalogs/exoplanets/namespaces?limit=50': problemResponse(404, 'NOT_FOUND')
			}).fetch
		);
		const outcome = await load(catalogEvent('exoplanets').event).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
	});

	it.each([
		[403, 'FORBIDDEN', 403],
		[503, 'DEPENDENCY_UNAVAILABLE', 503],
		[500, 'INTERNAL', 500]
	])('turns a %i %s into the %i page', async (status, code, expected) => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		vi.stubGlobal(
			'fetch',
			routes({ '/catalogs/heliophysics/namespaces?limit=50': problemResponse(status, code) }).fetch
		);
		const outcome = await load(catalogEvent().event).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, expected)).toBe(true);
	});

	it('ends the session once when the catalog and the root both meet a 401', async () => {
		const { event, cookies, sessionId } = catalogEvent();
		const api = fakeApi({
			'/catalogs/heliophysics': () => problemResponse(401, 'TOKEN_INVALID'),
			'/catalogs/heliophysics/namespaces?limit=50': () => problemResponse(401, 'TOKEN_INVALID')
		});
		vi.stubGlobal('fetch', api.fetch);
		const outcome = await load(event).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/login?status=expired&returnTo=%2Fcatalogs%2Fheliophysics'
		);
		// Both reads have met the 401 by now; only the first found the cookie to delete.
		await vi.waitFor(() => expect(api.calls).toHaveLength(2));
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(sessionStore().user(sessionId)).toBeUndefined();
		expect(cookies.writes.filter(({ name }) => name === 'huron_session')).toHaveLength(1);
	});
});
