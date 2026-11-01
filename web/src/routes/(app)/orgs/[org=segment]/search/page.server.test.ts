// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { describe, expect, it, vi } from 'vitest';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { load } from './+page.server';

vi.mock('$app/paths', () => ({ resolve: () => '/search' }));

vi.mock('$app/environment', () => ({
	dev: false,
	browser: false,
	building: false,
	version: 'test'
}));

describe('legacy organization search', () => {
	it('redirects supported filters to the central Search page', async () => {
		const { event } = signedInLoadEvent({
			url: 'http://localhost:4173/search?q=wind&label=mission&state=draft&cursor=next&unknown=ignored',
			routeId: '/(app)/orgs/[org=segment]/search',
			params: { org: 'helio' }
		});
		const outcome = await load(event).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && [outcome.status, outcome.location]).toEqual([
			303,
			'/search?organization=helio&q=wind&label=mission&state=draft&cursor=next'
		]);
	});
});
