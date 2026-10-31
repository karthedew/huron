// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	collectionFixture,
	commitFixture,
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
const COMMITS = [
	commitFixture({ id: '0192f2a4-0000-7000-8000-000000000502', base_version: 3, new_version: 4 }),
	commitFixture({ message: null })
];

function commitsEvent(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/commits${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/commits',
		params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' }
	}).event;
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	const api = fakeApi({
		[COLLECTION]: jsonResponse(collectionFixture()),
		[`/collections/${ID}/commits?limit=50`]: jsonResponse(pageFixture(COMMITS)),
		...overrides
	});
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

describe('/catalogs/[catalog]/collections/[identifier]/commits load', () => {
	it('returns the newest commits and whether older ones follow', async () => {
		routes();
		const data = await load(commitsEvent());
		expect(data).toEqual({ commits: COMMITS, nextCursor: null });
		expect(() => serializePageData(data)).not.toThrow();
	});

	it('reads the page its cursor names', async () => {
		routes({
			[`/collections/${ID}/commits?cursor=older&limit=50`]: jsonResponse(
				pageFixture(COMMITS.slice(1), 'oldest')
			)
		});
		expect(await load(commitsEvent('?cursor=older'))).toEqual({
			commits: COMMITS.slice(1),
			nextCursor: 'oldest'
		});
	});

	it('reads no commits of a draft, which takes none', async () => {
		const api = routes({
			[COLLECTION]: jsonResponse(collectionFixture({ state: 'draft', path: null }))
		});
		expect(await load(commitsEvent())).toEqual({ commits: [], nextCursor: null });
		expect(api.calls).toHaveLength(1);
	});

	it('starts over on the first page when the cursor is no longer accepted', async () => {
		routes({
			[`/collections/${ID}/commits?cursor=stale&limit=50`]: problemResponse(400, 'INVALID_CURSOR')
		});
		const outcome = await load(commitsEvent('?cursor=stale')).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/commits?notice=page_expired'
		);
	});

	it('shows the 500 page with the reference of an API failure', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		routes({
			[`/collections/${ID}/commits?limit=50`]: problemResponse(500, 'INTERNAL', {
				request_id: 'req-7'
			})
		});
		const outcome = await load(commitsEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 500) && outcome.body.id).toBe('req-7');
	});
});
