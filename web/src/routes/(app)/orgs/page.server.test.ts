// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	fakeApi,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse
} from '$lib/testing/api-fixtures';
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

const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });

function orgsEvent(path: string, cookies: Record<string, string> = {}) {
	return signedInLoadEvent({
		url: `http://localhost:4173${path}`,
		routeId: '/(app)/orgs',
		params: {},
		cookies
	}).event;
}

describe('/orgs load', () => {
	it('returns a page of the visible organizations and the remembered one', async () => {
		const api = fakeApi({
			'/organizations?limit=50': jsonResponse(pageFixture([GEO, HELIO], 'next-page'))
		});
		vi.stubGlobal('fetch', api.fetch);
		expect(await load(orgsEvent('/orgs', { huron_org: 'geo' }))).toEqual({
			organization: 'geo',
			organizationList: [GEO, HELIO],
			nextCursor: 'next-page'
		});
	});

	it('asks for the page the cursor names', async () => {
		const api = fakeApi({
			'/organizations?cursor=c2&limit=50': jsonResponse(pageFixture([HELIO]))
		});
		vi.stubGlobal('fetch', api.fetch);
		expect(await load(orgsEvent('/orgs?cursor=c2'))).toEqual({
			organization: null,
			organizationList: [HELIO],
			nextCursor: null
		});
		expect(api.calls).toHaveLength(1);
	});

	it('starts over with a notice when the cursor is no longer accepted', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/organizations?cursor=old&limit=50': problemResponse(400, 'INVALID_CURSOR') })
				.fetch
		);
		const outcome = await load(orgsEvent('/orgs?cursor=old')).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe('/orgs?notice=page_expired');
	});
});
