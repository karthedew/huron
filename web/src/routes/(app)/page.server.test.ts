// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Organization } from '$api/types';
import { sessionStore } from '$lib/server/sessions';
import {
	fakeFetch,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse
} from '$lib/testing/api-fixtures';
import { fakeServerLoadEvent } from '$lib/testing/events';
import { FakeCookies } from '$lib/testing/fake-cookies';
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

const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

function home(
	organizations: Organization[] | Response,
	remembered?: string,
	next: string | null = null
) {
	const answer =
		organizations instanceof Response
			? organizations
			: jsonResponse(pageFixture(organizations, next));
	const fake = fakeFetch(answer);
	vi.stubGlobal('fetch', fake.fetch);
	const { id } = sessionStore().create({
		huronToken: 'huron-token',
		tokenExpiresAt: new Date(Date.now() + 3_600_000).toISOString(),
		subject: 'sub-dave',
		name: 'Dave Example',
		groups: []
	});
	const cookies = new FakeCookies({
		huron_session: id,
		...(remembered === undefined ? {} : { huron_org: remembered })
	});
	const event = fakeServerLoadEvent({
		url: 'http://localhost:4173/',
		routeId: '/(app)',
		params: {},
		cookies,
		user: sessionStore().user(id)
	});
	return { event, calls: fake.calls };
}

async function redirectOf(promise: Promise<unknown>): Promise<string> {
	try {
		await promise;
	} catch (outcome) {
		if (isRedirect(outcome)) return outcome.location;
		throw outcome;
	}
	throw new Error('expected a redirect');
}

describe('/ load', () => {
	it('goes to the remembered organization when it is visible', async () => {
		const { event, calls } = home([HELIO, GEO], 'geo');
		expect(await redirectOf(load(event))).toBe('/orgs/geo');
		expect(calls[0].url).toBe('http://127.0.0.1:8197/api/v1/organizations?limit=500');
	});

	it('goes to the only visible organization otherwise', async () => {
		expect(await redirectOf(load(home([HELIO], 'geo').event))).toBe('/orgs/helio');
		expect(await redirectOf(load(home([HELIO], '../x').event))).toBe('/orgs/helio');
	});

	it('lists the organizations when there is a choice', async () => {
		expect(await load(home([HELIO, GEO]).event)).toEqual({
			organization: null,
			organizationList: [HELIO, GEO]
		});
		expect(await load(home([HELIO, GEO], 'astro').event)).toEqual({
			organization: 'astro',
			organizationList: [HELIO, GEO]
		});
	});

	it('does not treat the first of several pages as the only organization', async () => {
		expect(await load(home([HELIO], undefined, 'more').event)).toEqual({
			organization: null,
			organizationList: [HELIO]
		});
	});

	it('returns an empty list for the empty state', async () => {
		expect(await load(home([]).event)).toEqual({ organization: null, organizationList: [] });
	});

	it('shows the service error page when the API fails', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		try {
			await load(home(problemResponse(503, 'DEPENDENCY_UNAVAILABLE')).event);
		} catch (outcome) {
			expect(isHttpError(outcome, 503)).toBe(true);
			expect(log).toHaveBeenCalledOnce();
			return;
		}
		throw new Error('expected an HTTP error');
	});
});
