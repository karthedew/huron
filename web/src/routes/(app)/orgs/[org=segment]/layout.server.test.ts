// @vitest-environment node
import { isHttpError } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	fakeApi,
	jsonResponse,
	organizationFixture,
	problemResponse
} from '$lib/testing/api-fixtures';
import { signedInLoadEvent } from '$lib/testing/sessions';
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

afterEach(() => {
	vi.unstubAllGlobals();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

function organizationEvent(org: string) {
	return signedInLoadEvent({
		url: `http://localhost:4173/orgs/${org}`,
		routeId: '/(app)/orgs/[org=segment]',
		params: { org },
		cookies: { huron_org: 'geo' }
	}).event;
}

describe('/orgs/[org] layout load', () => {
	it('makes the organization current and returns its details', async () => {
		const helio = organizationFixture();
		const api = fakeApi({ '/organizations/helio': jsonResponse(helio) });
		vi.stubGlobal('fetch', api.fetch);
		expect(await load(organizationEvent('helio'))).toEqual({
			organization: 'helio',
			organizationDetails: helio
		});
		expect(api.calls).toHaveLength(1);
	});

	it('conceals an organization the user cannot see as not found', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ '/organizations/astro': problemResponse(404, 'NOT_FOUND') }).fetch
		);
		const outcome = await load(organizationEvent('astro')).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
	});
});
