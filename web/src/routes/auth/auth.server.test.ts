// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { sessionStore } from '$lib/server/sessions';
import { fakeFetch, jsonResponse, type FetchCall } from '$lib/testing/api-fixtures';
import { fakeRequestEvent } from '$lib/testing/events';
import { FakeCookies } from '$lib/testing/fake-cookies';
import { POST as logout } from '../logout/+server';
import { GET as callback } from './callback/+server';
import { GET as login } from './login/+server';

vi.mock('$env/dynamic/private', () => ({
	env: {
		ORIGIN: 'http://localhost:4173',
		HURON_API_URL: 'http://127.0.0.1:8197',
		HURON_WEB_OIDC_ISSUER: 'http://127.0.0.1:8199',
		HURON_WEB_OIDC_CLIENT_ID: 'huron-web',
		HURON_WEB_OIDC_CLIENT_SECRET: 'e2e-secret'
	}
}));
vi.mock('$app/environment', () => ({
	dev: false,
	browser: false,
	building: false,
	version: 'test'
}));

const IDP = 'http://127.0.0.1:8199';
const ORIGIN = 'http://localhost:4173';
const signIn = { nonce: '' };

function idToken(): string {
	const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
	const now = Math.floor(Date.now() / 1000);
	const claims = {
		iss: IDP,
		aud: ['huron-web', 'huron-cli'],
		azp: 'huron-web',
		sub: 'sub-erin',
		nonce: signIn.nonce,
		iat: now,
		exp: now + 300
	};
	return `${encode({ alg: 'RS256', typ: 'JWT' })}.${encode(claims)}.c2ln`;
}

function answer(call: FetchCall): Response {
	if (call.url === `${IDP}/.well-known/openid-configuration`) {
		return jsonResponse({
			issuer: IDP,
			authorization_endpoint: `${IDP}/authorize`,
			token_endpoint: `${IDP}/token`,
			end_session_endpoint: `${IDP}/logout`
		});
	}
	if (call.url === `${IDP}/token`) return jsonResponse({ id_token: idToken(), access_token: 'a' });
	if (call.url === 'http://127.0.0.1:8197/api/v1/auth/exchange') {
		return jsonResponse({
			huron_token: 'huron-token-for-erin',
			token_type: 'Bearer',
			expires_at: new Date(Date.now() + 8 * 3_600_000).toISOString(),
			subject: 'sub-erin',
			name: 'Erin Example',
			groups: ['helio-readers']
		});
	}
	throw new Error(`unexpected request to ${call.url}`);
}

beforeAll(() => {
	vi.stubGlobal('fetch', fakeFetch(answer).fetch);
});

afterAll(() => {
	vi.unstubAllGlobals();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

async function location(run: () => unknown): Promise<string> {
	try {
		await run();
	} catch (outcome) {
		if (isRedirect(outcome) && outcome.status === 303) return outcome.location;
		throw outcome;
	}
	throw new Error('expected a 303 redirect');
}

describe('the sign-in routes', () => {
	it('sign a user in, then out again', async () => {
		const cookies = new FakeCookies();
		const authorize = new URL(
			await location(() =>
				login(
					fakeRequestEvent({
						url: `${ORIGIN}/auth/login?returnTo=%2Forgs%2Fhelio`,
						routeId: '/auth/login',
						params: {},
						cookies
					})
				)
			)
		);
		expect(authorize.origin + authorize.pathname).toBe(`${IDP}/authorize`);
		expect(authorize.searchParams.get('client_id')).toBe('huron-web');
		const state = authorize.searchParams.get('state') ?? '';
		signIn.nonce = authorize.searchParams.get('nonce') ?? '';
		expect(cookies.get(`huron_oidc_${state.slice(0, 8)}`)).toBeDefined();

		const next = await location(() =>
			callback(
				fakeRequestEvent({
					url: `${ORIGIN}/auth/callback?code=the-code&state=${state}`,
					routeId: '/auth/callback',
					params: {},
					cookies
				})
			)
		);
		expect(next).toBe('/orgs/helio');
		const sessionId = cookies.get('huron_session') ?? '';
		expect(sessionStore().user(sessionId)?.name).toBe('Erin Example');

		const end = new URL(
			await location(() => logout(logoutEvent(cookies, { headers: { origin: ORIGIN } })))
		);
		expect(end.origin + end.pathname).toBe(`${IDP}/logout`);
		expect(end.searchParams.get('post_logout_redirect_uri')).toBe(
			`${ORIGIN}/login?status=signed-out`
		);
		expect(end.searchParams.has('id_token_hint')).toBe(false);
		expect(sessionStore().user(sessionId)).toBeUndefined();
		expect(cookies.get('huron_session')).toBeUndefined();
	});

	const FOREIGN_ORIGINS: Array<[string, Record<string, string>]> = [
		['another origin of the same site', { origin: 'http://localhost:19999' }],
		['an opaque origin', { origin: 'null' }],
		['no origin at all', {}]
	];

	it.each(FOREIGN_ORIGINS)(
		'refuse a logout from %s, with or without a form, and keep the session',
		async (_from, origin) => {
			const { id } = sessionStore().create({
				huronToken: 'huron-token-for-erin',
				tokenExpiresAt: new Date(Date.now() + 3_600_000).toISOString(),
				subject: 'sub-erin',
				name: 'Erin Example',
				groups: ['helio-readers']
			});
			const cookies = new FakeCookies({ huron_session: id });
			const form = { 'content-type': 'application/x-www-form-urlencoded' };
			for (const request of [
				{ headers: origin },
				{ headers: { ...origin, ...form }, body: 'from=elsewhere' }
			]) {
				expect((await logout(logoutEvent(cookies, request))).status).toBe(403);
			}
			expect(sessionStore().user(id)?.name).toBe('Erin Example');
			expect(cookies.writes).toEqual([]);
		}
	);
});

function logoutEvent(
	cookies: FakeCookies,
	request: { headers: Record<string, string>; body?: string }
) {
	return fakeRequestEvent({
		url: `${ORIGIN}/logout`,
		routeId: '/logout',
		params: {},
		cookies,
		request: { method: 'POST', ...request }
	});
}
