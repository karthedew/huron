// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { sessionStore } from '$lib/server/sessions';
import {
	collectionFixture,
	fakeApi,
	jsonResponse,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { GET } from './+server';

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
const COLLECTION = '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024';
/** The sidecar as the API sends it: canonical JSON and a final newline. */
const SIDECAR = '{"catalog":"heliophysics","huron":1,"metadata":{"title":"<b>ACE</b>"}}\n';

function sidecarRequest() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024/metadata.json',
		routeId: '/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/metadata.json',
		params: { catalog: 'heliophysics', identifier: 'solar-wind.ace.mag-l2-2024' }
	});
}

function routes(overrides: Record<string, FetchAnswer> = {}) {
	const api = fakeApi({
		[COLLECTION]: jsonResponse(collectionFixture()),
		[`/collections/${ID}/metadata.json`]: new Response(SIDECAR, {
			headers: {
				'content-type': 'application/json',
				'set-cookie': 'api=1',
				'x-api-only': 'leaks'
			}
		}),
		...overrides
	});
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

/** What the endpoint throws for a request, or `undefined` when it answers. */
async function thrownBy(event: ReturnType<typeof sidecarRequest>['event']): Promise<unknown> {
	try {
		await GET(event);
		return undefined;
	} catch (thrown) {
		return thrown;
	}
}

async function failure(overrides: Record<string, FetchAnswer>) {
	routes(overrides);
	return thrownBy(sidecarRequest().event);
}

describe('/catalogs/[catalog]/collections/[identifier]/metadata.json', () => {
	it("answers the API's file byte for byte, inline and sandboxed", async () => {
		routes();
		const response = await GET(sidecarRequest().event);
		expect(response.status).toBe(200);
		expect(await response.text()).toBe(SIDECAR);
		expect(Object.fromEntries(response.headers)).toEqual({
			'content-type': 'application/json',
			'content-disposition': 'inline',
			'content-security-policy': "default-src 'none'; sandbox",
			'cache-control': 'private, no-store'
		});
	});

	it('answers a draft, which has no such file, as not found without asking for it', async () => {
		const api = routes({
			[COLLECTION]: jsonResponse(collectionFixture({ state: 'draft', path: null }))
		});
		const outcome = await thrownBy(sidecarRequest().event);
		expect(isHttpError(outcome, 404) && outcome.body.message).toBe(
			"Not found, or you don't have access."
		);
		expect(api.calls).toHaveLength(1);
	});

	it('answers a refusal of the file as not found', async () => {
		for (const status of [404, 409]) {
			const outcome = await failure({
				[`/collections/${ID}/metadata.json`]: problemResponse(status, 'CONFLICT')
			});
			expect(isHttpError(outcome, 404), String(status)).toBe(true);
		}
	});

	it('answers a collection the user may not see as not found', async () => {
		const outcome = await failure({ [COLLECTION]: problemResponse(404, 'NOT_FOUND') });
		expect(isHttpError(outcome, 404)).toBe(true);
	});

	it('sends the user to sign in again when the token is no longer accepted', async () => {
		routes({ [COLLECTION]: problemResponse(401, 'TOKEN_INVALID') });
		const { event, sessionId } = sidecarRequest();
		const outcome = await thrownBy(event);
		expect(isRedirect(outcome) && outcome.location).toMatch(/^\/login\?status=expired&returnTo=/);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it('answers an outage with the 503 copy', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const outcome = await failure({
			[`/collections/${ID}/metadata.json`]: problemResponse(503, 'API_UNREACHABLE')
		});
		expect(isHttpError(outcome, 503)).toBe(true);
	});
});
