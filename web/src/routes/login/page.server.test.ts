// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { describe, expect, it, vi } from 'vitest';
import { fakeServerLoadEvent, fakeUser } from '$lib/testing/events';
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

function event(query: string, user = fakeUser()) {
	return fakeServerLoadEvent({
		url: `http://localhost:4173/login${query}`,
		routeId: '/login',
		params: {},
		user
	});
}

const anonymous = (query: string) =>
	fakeServerLoadEvent({
		url: `http://localhost:4173/login${query}`,
		routeId: '/login',
		params: {}
	});

describe('login page load', () => {
	it.each([
		['', { returnTo: '/', status: null, error: null }],
		['?status=signed-out', { returnTo: '/', status: 'signed-out', error: null }],
		[
			'?status=expired&returnTo=%2Forgs%2Fhelio',
			{ returnTo: '/orgs/helio', status: 'expired', error: null }
		],
		['?error=idp_unavailable', { returnTo: '/', status: null, error: 'idp_unavailable' }],
		['?error=config', { returnTo: '/', status: null, error: 'config' }]
	])('reads %j', (query, data) => {
		expect(load(anonymous(query))).toEqual(data);
	});

	it('never passes unknown codes or unsafe return paths on', () => {
		expect(load(anonymous('?status=<script>&error=Something%20bad&returnTo=//evil.com'))).toEqual({
			returnTo: '/',
			status: null,
			error: null
		});
	});

	it.each([
		['%2Forgs%2Fgeo', '/orgs/geo'],
		['%2Fx%2F..%2F%2Fevil.com', '/'],
		['%2F.%2F%2Fevil.com', '/'],
		['%2F%252e%2F%2Fevil.com', '/']
	])('sends a signed-in visitor with returnTo=%s on to %s', (returnTo, location) => {
		try {
			load(event(`?returnTo=${returnTo}`));
		} catch (outcome) {
			expect(isRedirect(outcome) && [outcome.status, outcome.location]).toEqual([303, location]);
			return;
		}
		throw new Error('expected a redirect');
	});
});
