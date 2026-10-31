// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Organization } from '$api/types';
import { shellOrganization } from '$lib/organizations';
import { emptySearch } from '$lib/search';
import {
	fakeApi,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse,
	type FetchAnswer
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
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });

function chooserEvent(query = '', cookies: Record<string, string> = {}) {
	return signedInLoadEvent({
		url: `http://localhost:4173/search${query}`,
		routeId: '/(app)/search',
		params: {},
		cookies
	});
}

function organizations(answer: FetchAnswer) {
	const fake = fakeApi({ '/organizations?limit=500': answer });
	vi.stubGlobal('fetch', fake.fetch);
	return fake;
}

function visible(list: Organization[], next: string | null = null) {
	return organizations(jsonResponse(pageFixture(list, next)));
}

describe('/search load', () => {
	it('asks which organization to search, for the text and labels but not the states', async () => {
		visible([GEO, HELIO]);
		const data = await load(chooserEvent('?q=%20wind%20&label=mission%3Dace&state=draft').event);
		expect(data).toEqual({
			organization: null,
			// What names each and its id: descriptions, counts and dates stay out of the page.
			organizationList: [GEO, HELIO].map(({ id, name, display_name }) => ({
				id,
				name,
				display_name
			})),
			search: { ...emptySearch(), q: 'wind', labels: [{ key: 'mission', value: 'ace' }] },
			errors: { q: null, label: null, form: null }
		});
	});

	it('returns the remembered organization for the shell', async () => {
		visible([GEO, HELIO]);
		const data = await load(chooserEvent('?q=wind', { huron_org: 'geo' }).event);
		expect(data.organization).toBe('geo');
	});

	it('leaves out what it cannot search, and says why', async () => {
		visible([GEO, HELIO]);
		const long = await load(chooserEvent(`?q=${'w'.repeat(201)}&label=level%3Dl2`).event);
		expect(long.search).toEqual({
			...emptySearch(),
			labels: [{ key: 'level', value: 'l2' }]
		});
		expect(long.errors.q).toBe('Use at most 200 characters; this text has 201.');
		const unread = await load(chooserEvent('?q=wind&label=mission').event);
		expect(unread.search).toEqual({ ...emptySearch(), q: 'wind' });
		expect(unread.errors.label).toBe('Write a label filter as key=value, for example mission=ace.');
	});

	it("sends a user with one organization straight to its search, the address's filters as written", async () => {
		visible([HELIO]);
		const outcome = await load(
			chooserEvent(`?q=${'w'.repeat(201)}&label=mission&state=draft&cursor=c2`).event
		).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && [outcome.status, outcome.location]).toEqual([
			303,
			`/orgs/helio/search?q=${'w'.repeat(201)}&label=mission`
		]);
		const plain = await load(chooserEvent().event).catch((thrown: unknown) => thrown);
		expect(isRedirect(plain) && plain.location).toBe('/orgs/helio/search');
	});

	it('asks even a user with one organization on its first page when more may follow', async () => {
		visible([HELIO], 'more');
		const data = await load(chooserEvent('?q=wind').event);
		expect(data.organizationList).toEqual([shellOrganization(HELIO)]);
	});

	it('has no organization to offer a user who can see none', async () => {
		visible([]);
		const data = await load(chooserEvent('?q=wind').event);
		expect(data.organizationList).toEqual([]);
	});

	it('fails as a page does when the organizations cannot be read', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		organizations(problemResponse(503, 'DEPENDENCY_UNAVAILABLE'));
		const outcome = await load(chooserEvent('?q=wind').event).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome) && outcome.status).toBe(503);
	});
});
