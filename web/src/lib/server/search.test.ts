// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoleGrant } from '$api/types';
import { emptySearch, searchResult } from '$lib/search';
import {
	catalogFixture,
	collectionFixture,
	fakeApi,
	hangingAnswer,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse,
	whoamiFixture,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { api } from './guard';
import { HuronApiError } from './huron-api';
import { draftAccess, exactMatch, maySeeDrafts, refusedSearch } from './search';
import { sessionStore } from './sessions';

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
const OTHER = catalogFixture({ id: '0192f2a4-0000-7000-8000-000000000999', name: 'other' });

function grant(role: string, scope: string, scopeId: string | null): RoleGrant {
	return { role, scope, scope_id: scopeId };
}

function searchEvent() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/catalogs/heliophysics/search?state=draft',
		routeId: '/(app)/catalogs/[catalog=segment]/(overview)/search',
		params: { catalog: 'heliophysics' }
	});
}

function stub(routes: Record<string, FetchAnswer>) {
	const fake = fakeApi(routes);
	vi.stubGlobal('fetch', fake.fetch);
	return fake;
}

describe('maySeeDrafts', () => {
	it.each([
		['a contributor of the catalog', [grant('contributor', 'catalog', HELIOPHYSICS.id)], true],
		['its catalog admin', [grant('catalog_admin', 'catalog', HELIOPHYSICS.id)], true],
		['an admin of its organization', [grant('org_admin', 'organization', HELIO.id)], true],
		['a platform admin', [grant('platform_admin', 'platform', null)], true],
		['a reader of the catalog', [grant('reader', 'catalog', HELIOPHYSICS.id)], false],
		['a contributor of another catalog', [grant('contributor', 'catalog', OTHER.id)], false],
		['someone without roles', [], false]
	])('lets %s search drafts: %s', (_, roles, expected) => {
		expect(maySeeDrafts({ roles, organizations: [HELIO] }, HELIOPHYSICS)).toBe(expected);
	});

	it("needs the catalog's organization among the visible ones for its admin", () => {
		const roles = [grant('org_admin', 'organization', HELIO.id)];
		expect(maySeeDrafts({ roles, organizations: [] }, HELIOPHYSICS)).toBe(false);
		expect(
			maySeeDrafts({ roles, organizations: [HELIO] }, { ...HELIOPHYSICS, organization: 'geo' })
		).toBe(false);
	});
});

describe('draftAccess', () => {
	it("reads the user's roles and organizations as the shell does, once per request", async () => {
		const roles = [grant('contributor', 'catalog', HELIOPHYSICS.id)];
		const fake = stub({
			'/auth/whoami': jsonResponse(whoamiFixture({ roles })),
			'/organizations?limit=500': jsonResponse(pageFixture([HELIO]))
		});
		const { event } = searchEvent();
		const client = api(event);
		expect(await draftAccess(event, client)).toEqual({ roles, organizations: [HELIO] });
		await draftAccess(event, client);
		expect(fake.calls).toHaveLength(2);
	});

	it('counts what it cannot read as nothing, and logs why', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		stub({
			'/auth/whoami': problemResponse(503, 'DEPENDENCY_UNAVAILABLE'),
			'/organizations?limit=500': problemResponse(500, 'INTERNAL')
		});
		const { event } = searchEvent();
		expect(await draftAccess(event, api(event))).toEqual({ roles: [], organizations: [] });
		expect(log).toHaveBeenCalledTimes(2);
	});

	it('ends the session when the API no longer accepts the token', async () => {
		stub({
			'/auth/whoami': problemResponse(401, 'TOKEN_INVALID'),
			'/organizations?limit=500': jsonResponse(pageFixture([HELIO]))
		});
		const { event, sessionId } = searchEvent();
		const outcome = await draftAccess(event, api(event)).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toMatch(/^\/login\?status=expired&/);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});
});

describe('exactMatch', () => {
	const MAG = collectionFixture();
	const LOOKUP = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024';

	it('looks up the collection the text names, and shows it as a result', async () => {
		const fake = stub({ [LOOKUP]: jsonResponse(MAG) });
		const { event } = searchEvent();
		const search = { ...emptySearch(), q: 'heliophysics.solar-wind.ace.mag-l2-2024' };
		const { signal } = new AbortController();
		expect(await exactMatch(event, api(event), 'heliophysics', search, { signal })).toEqual(
			searchResult(MAG)
		);
		expect(fake.calls).toHaveLength(1);
	});

	it('gives up without a word when its caller aborts the lookup', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		stub({ [LOOKUP]: hangingAnswer });
		const { event } = searchEvent();
		const caller = new AbortController();
		const search = { ...emptySearch(), q: 'solar-wind.ace.mag-l2-2024' };
		const lookup = exactMatch(event, api(event), 'heliophysics', search, {
			signal: caller.signal
		});
		caller.abort();
		expect(await lookup).toBeNull();
		expect(log).not.toHaveBeenCalled();
	});

	it('logs a lookup that fails on its own, and shows nothing', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		stub({ [LOOKUP]: problemResponse(503, 'DEPENDENCY_UNAVAILABLE') });
		const { event } = searchEvent();
		const search = { ...emptySearch(), q: 'solar-wind.ace.mag-l2-2024' };
		const { signal } = new AbortController();
		expect(await exactMatch(event, api(event), 'heliophysics', search, { signal })).toBeNull();
		expect(log).toHaveBeenCalledTimes(1);
	});
});

describe('refusedSearch', () => {
	it('names the fields of a refusal and nothing for other failures', () => {
		const refusal = (context: Record<string, unknown>) =>
			new HuronApiError({
				status: 422,
				code: 'REQUEST_INVALID',
				title: 'Request invalid',
				context
			});
		expect(
			refusedSearch(refusal({ problems: [{ path: '/query/q' }, { path: '/query/label/1' }] }))
		).toEqual({
			q: "The Huron service didn't accept this text.",
			label: "The Huron service didn't accept these label filters.",
			form: null
		});
		expect(
			refusedSearch(refusal({ problems: [{ path: '/query/q' }, { path: '/query/state/0' }] }))
		).toEqual({
			q: "The Huron service didn't accept this text.",
			label: null,
			form: "The Huron service didn't accept this search."
		});
		expect(refusedSearch(refusal({ problems: 'not a list' }))?.form).toBe(
			"The Huron service didn't accept this search."
		);
		expect(
			refusedSearch(new HuronApiError({ status: 503, code: 'API_UNREACHABLE', title: 'Down' }))
		).toBeNull();
		expect(refusedSearch(new Error('bug'))).toBeNull();
	});
});
