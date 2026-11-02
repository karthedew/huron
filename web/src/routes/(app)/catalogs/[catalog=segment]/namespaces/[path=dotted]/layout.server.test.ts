// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	collectionFixture,
	fakeApi,
	jsonResponse,
	namespaceFixture,
	pageFixture,
	problemResponse
} from '$lib/testing/api-fixtures';
import { serializePageData } from '$lib/testing/page-data';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { load } from './+layout.server';
vi.mock('$env/dynamic/private', () => ({
	env: {
		ORIGIN: 'http://localhost:4173',
		HURON_API_URL: 'http://127.0.0.1:8197',
		HURON_WEB_OIDC_ISSUER: 'http://127.0.0.1:8199',
		HURON_WEB_OIDC_CLIENT_ID: 'huron-web',
		HURON_WEB_MOUNT_PREFIX: '/projects/huron'
	}
}));
vi.mock('$app/environment', () => ({
	dev: false,
	browser: false,
	building: false,
	version: 'test'
}));
afterEach(async () => {
	vi.unstubAllGlobals();
	(await import('$lib/server/config')).resetConfig();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

const route = '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]';
function event() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/catalogs/heliophysics/namespaces/solar-wind',
		routeId: route,
		params: { catalog: 'heliophysics', path: 'solar-wind' }
	}).event;
}
describe('namespace shared layout', () => {
	it('returns the namespace, share path and bounded serializable Explorer trail', async () => {
		const namespace = namespaceFixture();
		const collection = collectionFixture({ metadata: { ['__proto__']: 'value' } });
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/catalogs/heliophysics/namespaces/solar-wind': jsonResponse(namespace),
				'/catalogs/heliophysics/namespaces?parent=solar-wind&limit=50': jsonResponse(
					pageFixture([])
				),
				'/catalogs/heliophysics/namespaces/solar-wind/collections?limit=50': jsonResponse(
					pageFixture([collection])
				)
			}).fetch
		);
		const data = await load(event());
		expect(data.namespace).toEqual(namespace);
		expect(data.sharePath).toBe('/projects/huron/helio/heliophysics/solar-wind');
		expect(data.trail).toHaveLength(1);
		expect(() => serializePageData(data)).not.toThrow();
	});
	it('uses the declared organization share root', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/catalogs/heliophysics/namespaces/solar-wind': jsonResponse(
					namespaceFixture({ share_root: '/data/huron' })
				),
				'/catalogs/heliophysics/namespaces?parent=solar-wind&limit=50': jsonResponse(
					pageFixture([])
				),
				'/catalogs/heliophysics/namespaces/solar-wind/collections?limit=50': jsonResponse(
					pageFixture([])
				)
			}).fetch
		);
		expect((await load(event())).sharePath).toBe('/data/huron/helio/heliophysics/solar-wind');
	});
	it.each([403, 404, 503])(
		'does not load a trail when namespace read fails with %s',
		async (status) => {
			const api = fakeApi({
				'/catalogs/heliophysics/namespaces/solar-wind': problemResponse(status, 'NOT_FOUND')
			});
			vi.stubGlobal('fetch', api.fetch);
			const result = await load(event()).catch((error: unknown) => error);
			expect(isHttpError(result)).toBe(true);
			expect(api.calls).toHaveLength(1);
		}
	);
	it('ends an expired session before reading the trail', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'/catalogs/heliophysics/namespaces/solar-wind': problemResponse(401, 'TOKEN_INVALID')
			}).fetch
		);
		expect(isRedirect(await load(event()).catch((error: unknown) => error))).toBe(true);
	});
});
