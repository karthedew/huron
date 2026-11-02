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
		url: 'http://localhost:4173/catalogs/heliophysics/access',
		routeId: '/(app)/catalogs/[catalog=segment]/(overview)/access',
		params: { catalog: 'heliophysics' }
	}).event;
}

const SOURCES = [
	{ role: 'platform_admin', group: 'huron-platform-admins', scope: 'platform' },
	{ role: 'org_admin', group: 'helio-org-admins', scope: 'organization' },
	{ role: 'reader', group: 'helio-readers', scope: 'organization' },
	{ role: 'reader', group: 'helio-readers', scope: 'catalog' },
	{ role: 'reader', group: 'web-readers', scope: 'catalog' }
];

describe('/catalogs/[catalog]/access load', () => {
	it('returns the groups of every role by where each was granted', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/catalogs/heliophysics/grants/sources': jsonResponse({ items: SOURCES }) }).fetch
		);
		const data = await load(accessEvent());
		expect(data).toEqual({
			access: [
				{
					role: 'platform_admin',
					sources: [{ scope: 'platform', groups: ['huron-platform-admins'] }]
				},
				{ role: 'org_admin', sources: [{ scope: 'organization', groups: ['helio-org-admins'] }] },
				{ role: 'catalog_admin', sources: [] },
				{ role: 'contributor', sources: [] },
				{
					role: 'reader',
					sources: [
						{ scope: 'organization', groups: ['helio-readers'] },
						{ scope: 'catalog', groups: ['helio-readers', 'web-readers'] }
					]
				}
			]
		});
		expect(() => serializePageData(data)).not.toThrow();
	});

	it('keeps the page when the API refuses the groups', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/catalogs/heliophysics/grants/sources': problemResponse(403, 'FORBIDDEN') }).fetch
		);
		expect(await load(accessEvent())).toEqual({ access: null });
	});

	it('conceals a catalog that is gone as not found', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/catalogs/heliophysics/grants/sources': problemResponse(404, 'NOT_FOUND') }).fetch
		);
		const outcome = await load(accessEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
	});
});
