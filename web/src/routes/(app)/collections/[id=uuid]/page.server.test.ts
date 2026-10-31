// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LINKED_COLLECTION_GONE } from '$lib/error-copy';
import { sessionStore } from '$lib/server/sessions';
import {
	collectionFixture,
	fakeApi,
	jsonResponse,
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

const ID = '0192f2a4-0000-7000-8000-000000000401';

function linkEvent(id = ID) {
	return signedInLoadEvent({
		url: `http://localhost:4173/collections/${id}`,
		routeId: '/(app)/collections/[id=uuid]',
		params: { id }
	});
}

async function outcome(answer: FetchAnswer, id = ID) {
	const api = fakeApi({ [`/collections/${id}`]: answer });
	vi.stubGlobal('fetch', api.fetch);
	const request = linkEvent(id);
	return {
		...request,
		calls: api.calls,
		thrown: await load(request.event).then(
			() => undefined,
			(thrown: unknown) => thrown
		)
	};
}

describe('/collections/[id] load', () => {
	it("sends the browser on to the collection's page by its identifier", async () => {
		const { thrown } = await outcome(jsonResponse(collectionFixture()));
		expect(isRedirect(thrown) && [thrown.status, thrown.location]).toEqual([
			303,
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		]);
	});

	it('keeps a namespace named like its catalog in the address', async () => {
		const collection = collectionFixture({
			catalog: 'geoscience',
			namespace: 'geoscience.ocean',
			identifier: 'geoscience.geoscience.ocean.sst-2024'
		});
		const { thrown } = await outcome(jsonResponse(collection));
		expect(isRedirect(thrown) && thrown.location).toBe(
			'/catalogs/geoscience/collections/geoscience.ocean.sst-2024'
		);
	});

	it('says a collection it cannot show may have been deleted', async () => {
		for (const status of [403, 404]) {
			const { thrown } = await outcome(problemResponse(status, 'NOT_FOUND'));
			expect(isHttpError(thrown, 404), String(status)).toBe(true);
			expect(isHttpError(thrown) && thrown.body).toEqual({
				message: 'Not found, deleted, or you do not have access.',
				code: LINKED_COLLECTION_GONE
			});
		}
	});

	it('sends the user to sign in again when the token is no longer accepted', async () => {
		const { thrown, sessionId } = await outcome(problemResponse(401, 'TOKEN_INVALID'));
		expect(isRedirect(thrown) && thrown.location).toBe(
			`/login?status=expired&returnTo=%2Fcollections%2F${ID}`
		);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it('shows an outage as such, not as a missing collection', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const { thrown } = await outcome(problemResponse(503, 'API_UNREACHABLE'));
		expect(isHttpError(thrown, 503)).toBe(true);
	});

	it('reads the collection by an id in capitals too', async () => {
		const upper = ID.toUpperCase();
		const { thrown, calls } = await outcome(jsonResponse(collectionFixture()), upper);
		expect(isRedirect(thrown)).toBe(true);
		expect(calls[0].url).toContain(`/collections/${upper}`);
	});
});
