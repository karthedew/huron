// @vitest-environment node
import { isHttpError } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fakeApi, jsonResponse, problemResponse } from '$lib/testing/api-fixtures';
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
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

function accessEvent() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/orgs/helio/access',
		routeId: '/(app)/orgs/[org=segment]/access',
		params: { org: 'helio' }
	}).event;
}

const GROUPS = {
	org_admin: ['helio-org-admins'],
	catalog_admin: ['helio-catalog-admins'],
	contributor: [],
	reader: ['helio-readers']
};

describe('/orgs/[org]/access load', () => {
	it("returns the groups of the organization's roles", async () => {
		vi.stubGlobal('fetch', fakeApi({ '/organizations/helio/grants': jsonResponse(GROUPS) }).fetch);
		const data = await load(accessEvent());
		expect(data).toEqual({ groups: GROUPS });
		expect(() => serializePageData(data)).not.toThrow();
	});

	it('keeps the page when the API refuses the groups', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/organizations/helio/grants': problemResponse(403, 'FORBIDDEN') }).fetch
		);
		expect(await load(accessEvent())).toEqual({ groups: null });
	});

	it('conceals an organization that is gone as not found', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/organizations/helio/grants': problemResponse(404, 'NOT_FOUND') }).fetch
		);
		const outcome = await load(accessEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
	});
});
