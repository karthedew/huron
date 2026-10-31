// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ROLE_ABILITIES } from '$lib/roles';
import { sessionStore } from '$lib/server/sessions';
import {
	catalogFixture,
	fakeApi,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse,
	whoamiFixture
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
	vi.restoreAllMocks();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

const HELIO = organizationFixture();
const HELIOPHYSICS = catalogFixture();

function accountEvent() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/account',
		routeId: '/(app)/account',
		params: {},
		cookies: { huron_org: 'helio' }
	});
}

describe('/account load', () => {
	it('describes the roles with the names of their scopes', async () => {
		const api = fakeApi({
			'/auth/whoami': jsonResponse(
				whoamiFixture({
					roles: [
						{ scope: 'catalog', scope_id: HELIOPHYSICS.id, role: 'contributor' },
						{ scope: 'organization', scope_id: HELIO.id, role: 'org_admin' }
					]
				})
			),
			'/organizations?limit=500': jsonResponse(pageFixture([HELIO])),
			'/catalogs?limit=500': jsonResponse(pageFixture([HELIOPHYSICS]))
		});
		vi.stubGlobal('fetch', api.fetch);
		expect(await load(accountEvent().event)).toEqual({
			organization: 'helio',
			roleSentences: [
				{
					key: `organization:${HELIO.id}:org_admin`,
					lead: 'You are an organization administrator of',
					target: {
						kind: 'organization',
						name: 'helio',
						label: 'Heliophysics Division',
						context: null
					},
					abilities: `You can ${ROLE_ABILITIES.org_admin}.`
				},
				{
					key: `catalog:${HELIOPHYSICS.id}:contributor`,
					lead: 'You are a contributor to',
					target: {
						kind: 'catalog',
						name: 'heliophysics',
						label: 'Heliophysics',
						context: 'Heliophysics Division'
					},
					abilities: `You can ${ROLE_ABILITIES.contributor}.`
				}
			]
		});
		expect(api.calls).toHaveLength(3);
	});

	it('still shows the account when the API fails, and logs the failures', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/auth/whoami': problemResponse(503, 'DEPENDENCY_UNAVAILABLE'),
				'/organizations?limit=500': problemResponse(503, 'DEPENDENCY_UNAVAILABLE'),
				'/catalogs?limit=500': problemResponse(503, 'DEPENDENCY_UNAVAILABLE')
			}).fetch
		);
		expect(await load(accountEvent().event)).toEqual({
			organization: 'helio',
			roleSentences: null
		});
		expect(log).toHaveBeenCalledTimes(3);
	});

	it('names what it can when only the catalogs are missing', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/auth/whoami': jsonResponse(
					whoamiFixture({
						roles: [{ scope: 'catalog', scope_id: HELIOPHYSICS.id, role: 'reader' }]
					})
				),
				'/organizations?limit=500': jsonResponse(pageFixture([HELIO])),
				'/catalogs?limit=500': problemResponse(500, 'INTERNAL')
			}).fetch
		);
		const data = await load(accountEvent().event);
		expect(data.roleSentences?.[0].target).toEqual({
			kind: 'unresolved',
			label: 'catalog 000000000101'
		});
	});

	it('ends the session when the Huron token is no longer accepted', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/auth/whoami': problemResponse(401, 'TOKEN_INVALID'),
				'/organizations?limit=500': jsonResponse(pageFixture([HELIO])),
				'/catalogs?limit=500': jsonResponse(pageFixture([]))
			}).fetch
		);
		const { sessionId, event } = accountEvent();
		const outcome = await load(event).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/login?status=expired&returnTo=%2Faccount'
		);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});
});
