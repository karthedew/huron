// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	collectionFixture,
	fakeApi,
	fileFixture,
	jsonResponse,
	pageFixture,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { serializePageData } from '$lib/testing/page-data';
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

const ID = '0192f2a4-0000-7000-8000-000000000401';
const COLLECTION = '/catalogs/heliophysics/collections/fields.run001';
const FRAMES = [
	fileFixture({ rel_path: 'frames/frame-0001.dat' }),
	fileFixture({ rel_path: 'frames/frame-0002.dat' })
];

function filesEvent(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics/collections/fields.run001/files${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/files',
		params: { catalog: 'heliophysics', identifier: 'fields.run001' }
	}).event;
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	const api = fakeApi({
		[COLLECTION]: jsonResponse(collectionFixture({ file_count: 120 })),
		[`/collections/${ID}/files?limit=50`]: jsonResponse(pageFixture(FRAMES, 'next-files')),
		...overrides
	});
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

describe('/catalogs/[catalog]/collections/[identifier]/files load', () => {
	it('returns the first page of recorded files and the cursor of the next', async () => {
		routes();
		const data = await load(filesEvent());
		expect(data).toEqual({ files: FRAMES, nextCursor: 'next-files' });
		expect(() => serializePageData(data)).not.toThrow();
	});

	it('reads the page its cursor names', async () => {
		const api = routes({
			[`/collections/${ID}/files?cursor=next-files&limit=50`]: jsonResponse(pageFixture([]))
		});
		expect(await load(filesEvent('?cursor=next-files'))).toEqual({ files: [], nextCursor: null });
		expect(api.calls.at(-1)?.url).toContain('cursor=next-files');
	});

	it('reads no files of a draft, which has none', async () => {
		const api = routes({
			[COLLECTION]: jsonResponse(collectionFixture({ state: 'draft', path: null, file_count: 0 }))
		});
		expect(await load(filesEvent())).toEqual({ files: [], nextCursor: null });
		expect(api.calls).toHaveLength(1);
	});

	it('starts over on the first page when the cursor is no longer accepted', async () => {
		routes({
			[`/collections/${ID}/files?cursor=stale&limit=50`]: problemResponse(400, 'INVALID_CURSOR')
		});
		const outcome = await load(filesEvent('?cursor=stale')).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/catalogs/heliophysics/collections/fields.run001/files?notice=page_expired'
		);
	});

	it('shows a collection that does not exist as not found', async () => {
		const api = routes({ [COLLECTION]: problemResponse(404, 'NOT_FOUND') });
		const outcome = await load(filesEvent()).catch((thrown: unknown) => thrown);
		expect(isHttpError(outcome, 404)).toBe(true);
		expect(api.calls).toHaveLength(1);
	});
});
