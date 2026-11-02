// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HuronApi } from '$lib/server/huron-api';
import { sessionStore } from '$lib/server/sessions';
import {
	fakeFetch,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse,
	whoamiFixture,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { fakeServerLoadEvent } from '$lib/testing/events';
import { FakeCookies } from '$lib/testing/fake-cookies';
import { load } from './+layout.server';

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

const API = 'http://127.0.0.1:8197/api/v1';

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

function signedInEvent(path = '/', browserCookies: Record<string, string> = {}) {
	const { id } = sessionStore().create({
		huronToken: 'huron-token',
		tokenExpiresAt: new Date(Date.now() + 3_600_000).toISOString(),
		subject: 'sub-dave',
		name: 'Dave Example',
		groups: ['helio-contributors', 'geo-readers']
	});
	const cookies = new FakeCookies({ ...browserCookies, huron_session: id });
	const user = sessionStore().user(id);
	return {
		id,
		cookies,
		event: fakeServerLoadEvent({
			url: `http://localhost:4173${path}`,
			routeId: '/(app)',
			params: {},
			cookies,
			user
		})
	};
}

function api(answers: { organizations: FetchAnswer; whoami: FetchAnswer }) {
	const fake = fakeFetch((call) => {
		const answer = call.url.startsWith(`${API}/organizations`)
			? answers.organizations
			: answers.whoami;
		if (answer instanceof Error) throw answer;
		return typeof answer === 'function' ? answer(call) : answer.clone();
	});
	vi.stubGlobal('fetch', fake.fetch);
	return fake.calls;
}

describe('(app) layout load', () => {
	it('returns the user, the visible organizations and the roles', async () => {
		const organizations = [organizationFixture(), organizationFixture({ id: 'o2', name: 'geo' })];
		const calls = api({
			organizations: jsonResponse(pageFixture(organizations)),
			whoami: jsonResponse(whoamiFixture())
		});
		const { event } = signedInEvent();
		expect(await load(event)).toEqual({
			user: event.locals.user,
			// What names each and its id: descriptions, counts and dates stay out of every page.
			organizations: organizations.map(({ id, name, display_name }) => ({
				id,
				name,
				display_name
			})),
			organizationsUnavailable: false,
			roles: whoamiFixture().roles,
			rolesUnavailable: false,
			rememberedOrganization: null
		});
		expect(calls.map(({ url }) => url).sort()).toEqual([
			`${API}/auth/whoami`,
			`${API}/organizations?limit=500`
		]);
	});

	it('passes on the remembered organization only when it is a well-formed name', async () => {
		api({ organizations: jsonResponse(pageFixture([])), whoami: jsonResponse(whoamiFixture()) });
		const remembered = await load(signedInEvent('/', { huron_org: 'geo' }).event);
		expect(remembered.rememberedOrganization).toBe('geo');
		const malformed = await load(signedInEvent('/', { huron_org: 'Not a name' }).event);
		expect(malformed.rememberedOrganization).toBeNull();
	});

	it('still renders the shell when the API fails, and logs each failure', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		api({
			organizations: problemResponse(503, 'DEPENDENCY_UNAVAILABLE'),
			whoami: new TypeError('fetch failed')
		});
		const { event } = signedInEvent('/orgs/helio');
		expect(await load(event)).toMatchObject({
			organizations: [],
			organizationsUnavailable: true,
			roles: [],
			rolesUnavailable: true
		});
		expect(log.mock.calls.map(([, entry]) => entry)).toEqual([
			expect.objectContaining({ status: 503, code: 'DEPENDENCY_UNAVAILABLE', path: '/orgs/helio' }),
			expect.objectContaining({ status: 503, code: 'API_UNREACHABLE', path: '/orgs/helio' })
		]);
	});

	it('fails loudly on an error that is not an API failure', async () => {
		api({ organizations: jsonResponse(pageFixture([])), whoami: jsonResponse(whoamiFixture()) });
		const bug = new TypeError('a bug');
		vi.spyOn(HuronApi.prototype, 'whoami').mockRejectedValue(bug);
		await expect(load(signedInEvent().event)).rejects.toBe(bug);
	});

	it('ends the session when the Huron token is no longer accepted', async () => {
		api({
			organizations: jsonResponse(pageFixture([])),
			whoami: problemResponse(401, 'TOKEN_INVALID')
		});
		const { id, cookies, event } = signedInEvent('/orgs/helio');
		try {
			await load(event);
		} catch (outcome) {
			expect(isRedirect(outcome) && outcome.location).toBe(
				'/login?status=expired&returnTo=%2Forgs%2Fhelio'
			);
			expect(sessionStore().user(id)).toBeUndefined();
			expect(cookies.lastWrite('huron_session')?.value).toBeNull();
			return;
		}
		throw new Error('expected a redirect');
	});
});
