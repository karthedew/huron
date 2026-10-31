// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import { catalogFixture, fakeApi, jsonResponse, pageFixture } from '$lib/testing/api-fixtures';
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
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

function catalogsEvent(path: string) {
	return signedInLoadEvent({
		url: `http://localhost:4173${path}`,
		routeId: '/(app)/orgs/[org=segment]',
		params: { org: 'helio' }
	}).event;
}

describe('/orgs/[org] page load', () => {
	it("returns a page of the organization's catalogs", async () => {
		const catalogs = [catalogFixture(), catalogFixture({ id: 'c2', name: 'space-weather' })];
		const api = fakeApi({
			'/catalogs?organization=helio&limit=50': jsonResponse(pageFixture(catalogs, 'more'))
		});
		vi.stubGlobal('fetch', api.fetch);
		expect(await load(catalogsEvent('/orgs/helio'))).toEqual({ catalogs, nextCursor: 'more' });
	});

	it('asks for the page the cursor names', async () => {
		const api = fakeApi({
			'/catalogs?organization=helio&cursor=c2&limit=50': jsonResponse(pageFixture([]))
		});
		vi.stubGlobal('fetch', api.fetch);
		expect(await load(catalogsEvent('/orgs/helio?cursor=c2'))).toEqual({
			catalogs: [],
			nextCursor: null
		});
		expect(api.calls).toHaveLength(1);
	});
});
