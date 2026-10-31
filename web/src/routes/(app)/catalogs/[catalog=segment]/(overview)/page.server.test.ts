// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	catalogFixture,
	fakeApi,
	jsonResponse,
	namespaceFixture,
	pageFixture,
	problemResponse
} from '$lib/testing/api-fixtures';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { load as layoutLoad } from '../+layout.server';
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
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

function overviewEvent(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/(overview)',
		params: { catalog: 'heliophysics' }
	}).event;
}

const ROOT = [namespaceFixture(), namespaceFixture({ id: 'n2', name: 'fields', path: 'fields' })];

describe('/catalogs/[catalog] overview load', () => {
	it('returns the first page of top-level namespaces', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/catalogs/heliophysics/namespaces?limit=50': jsonResponse(pageFixture(ROOT, 'n3'))
			}).fetch
		);
		expect(await load(overviewEvent())).toEqual({ namespaces: ROOT, nextCursor: 'n3' });
	});

	it('shares its first page with the layout that loads the explorer root', async () => {
		const api = fakeApi({
			'/catalogs/heliophysics': jsonResponse(catalogFixture()),
			'/catalogs?organization=helio&limit=100': jsonResponse(pageFixture([catalogFixture()])),
			'/catalogs/heliophysics/namespaces?limit=50': jsonResponse(pageFixture(ROOT))
		});
		vi.stubGlobal('fetch', api.fetch);
		const event = overviewEvent();
		await Promise.all([layoutLoad(event), load(event)]);
		const reads = api.calls.filter(({ url }) => url.includes('/namespaces'));
		expect(reads).toHaveLength(1);
	});

	it('asks for the page the cursor names', async () => {
		const api = fakeApi({
			'/catalogs/heliophysics/namespaces?cursor=n3&limit=50': jsonResponse(pageFixture([]))
		});
		vi.stubGlobal('fetch', api.fetch);
		expect(await load(overviewEvent('?cursor=n3'))).toEqual({ namespaces: [], nextCursor: null });
	});

	it('restarts a list whose cursor the API no longer accepts', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/catalogs/heliophysics/namespaces?cursor=stale&limit=50': problemResponse(
					400,
					'INVALID_CURSOR'
				)
			}).fetch
		);
		const outcome = await load(overviewEvent('?cursor=stale')).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/catalogs/heliophysics?notice=page_expired'
		);
	});
});
