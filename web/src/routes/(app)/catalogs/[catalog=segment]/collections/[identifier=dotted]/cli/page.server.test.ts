// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	collectionFixture,
	fakeApi,
	jsonResponse,
	problemResponse
} from '$lib/testing/api-fixtures';
import { serializePageData } from '$lib/testing/page-data';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { load } from './+page.server';
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

function event() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/cli',
		routeId: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/cli',
		params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' }
	}).event;
}
const path = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024';
describe('collection CLI load', () => {
	it.each([{ problems: [] }, { problems: [{ path: '/', message: 'Required', rule: 'required' }] }])(
		'returns only presence of problems',
		async ({ problems }) => {
			vi.stubGlobal(
				'fetch',
				fakeApi({
					[path]: jsonResponse(
						collectionFixture({ problems, metadata: { ['__proto__']: 'unsafe' } })
					)
				}).fetch
			);
			const data = await load(event());
			expect(data).toEqual({ hasProblems: problems.length > 0 });
			expect(() => serializePageData(data)).not.toThrow();
		}
	);
	it.each([403, 404])('maps inaccessible collection status %s', async (status) => {
		vi.stubGlobal('fetch', fakeApi({ [path]: problemResponse(status, 'NOT_FOUND') }).fetch);
		expect(isHttpError(await load(event()).catch((error: unknown) => error), status)).toBe(true);
	});
	it('ends an expired session', async () => {
		vi.stubGlobal('fetch', fakeApi({ [path]: problemResponse(401, 'TOKEN_INVALID') }).fetch);
		expect(isRedirect(await load(event()).catch((error: unknown) => error))).toBe(true);
	});
});
