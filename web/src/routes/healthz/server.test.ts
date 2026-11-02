// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { fakeRequestEvent } from '$lib/testing/events';
import { GET } from './+server';

describe('GET /healthz', () => {
	it('answers ok', async () => {
		const response = await GET(
			fakeRequestEvent({ url: 'http://localhost:4173/healthz', routeId: '/healthz', params: {} })
		);
		expect(response.status).toBe(200);
		expect(await response.json()).toEqual({ status: 'ok' });
	});
});
