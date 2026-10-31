// @vitest-environment node
import * as devalue from 'devalue';
import { describe, expect, it, vi } from 'vitest';
import { integerDigits, isRecord } from '$lib/json';
import {
	auditFixture,
	catalogFixture,
	collectionFixture,
	commitFixture,
	connectionReset,
	fakeFetch,
	fileFixture,
	hangingAnswer,
	jsonResponse,
	namespaceFixture,
	organizationFixture,
	pageFixture,
	problemResponse,
	schemaFixture,
	whoamiFixture,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { HuronApi, HuronApiError, exchange, type HuronApiOptions } from './huron-api';

const BASE = 'http://api.internal:8080';
const TOKEN = 'huron-token-value';

function client(answers: FetchAnswer[], options: Partial<HuronApiOptions> = {}) {
	const fake = fakeFetch(...answers);
	const api = new HuronApi({
		baseUrl: BASE,
		token: TOKEN,
		timeoutMs: 1000,
		fetch: fake.fetch,
		...options
	});
	return { api, calls: fake.calls };
}

async function failure(promise: Promise<unknown>): Promise<HuronApiError> {
	try {
		await promise;
	} catch (error) {
		if (error instanceof HuronApiError) return error;
		throw error;
	}
	throw new Error('expected a HuronApiError');
}

const ID = '0192f2a4-0000-7000-8000-000000000401';

describe('HuronApi URLs', () => {
	const page = pageFixture([]);
	it.each<[string, (api: HuronApi) => Promise<unknown>, string, unknown]>([
		['whoami', (api) => api.whoami(), '/api/v1/auth/whoami', whoamiFixture()],
		[
			'organizations',
			(api) => api.organizations({ cursor: 'c1', limit: 500 }),
			'/api/v1/organizations?cursor=c1&limit=500',
			page
		],
		[
			'organization',
			(api) => api.organization('helio'),
			'/api/v1/organizations/helio',
			organizationFixture()
		],
		[
			'catalogs',
			(api) => api.catalogs({ organization: 'helio', limit: 100 }),
			'/api/v1/catalogs?organization=helio&limit=100',
			page
		],
		[
			'catalog',
			(api) => api.catalog('heliophysics'),
			'/api/v1/catalogs/heliophysics',
			catalogFixture()
		],
		[
			'catalogSchema',
			(api) => api.catalogSchema('heliophysics'),
			'/api/v1/catalogs/heliophysics/schema',
			{ type: 'object' }
		],
		[
			'catalogGrants',
			(api) => api.catalogGrants('heliophysics'),
			'/api/v1/catalogs/heliophysics/grants',
			{ platform_admin: [], org_admin: [], catalog_admin: [], contributor: [], reader: ['r'] }
		],
		[
			'catalogLog',
			(api) => api.catalogLog('heliophysics', { cursor: 'n' }),
			'/api/v1/catalogs/heliophysics/log?cursor=n',
			pageFixture([auditFixture()])
		],
		[
			'namespaces at the root',
			(api) => api.namespaces('heliophysics', ''),
			'/api/v1/catalogs/heliophysics/namespaces',
			page
		],
		[
			'namespaces under a parent',
			(api) => api.namespaces('heliophysics', 'solar-wind.ace', { limit: 50 }),
			'/api/v1/catalogs/heliophysics/namespaces?parent=solar-wind.ace&limit=50',
			pageFixture([namespaceFixture()])
		],
		[
			'namespace',
			(api) => api.namespace('heliophysics', 'solar-wind.ace'),
			'/api/v1/catalogs/heliophysics/namespaces/solar-wind.ace',
			namespaceFixture()
		],
		[
			'namespaceCollections',
			(api) => api.namespaceCollections('heliophysics', 'fields', { cursor: 'p2', limit: 50 }),
			'/api/v1/catalogs/heliophysics/namespaces/fields/collections?cursor=p2&limit=50',
			pageFixture([collectionFixture()])
		],
		[
			'collectionByIdentifier',
			(api) => api.collectionByIdentifier('heliophysics', 'solar-wind.ace.mag-l2-2024'),
			'/api/v1/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024',
			collectionFixture()
		],
		['collection', (api) => api.collection(ID), `/api/v1/collections/${ID}`, collectionFixture()],
		['collectionSchema', (api) => api.collectionSchema(ID), `/api/v1/collections/${ID}/schema`, {}],
		[
			'files',
			(api) => api.files(ID, { limit: 50 }),
			`/api/v1/collections/${ID}/files?limit=50`,
			pageFixture([fileFixture()], 'next')
		],
		[
			'commits',
			(api) => api.commits(ID),
			`/api/v1/collections/${ID}/commits`,
			pageFixture([commitFixture(), commitFixture({ message: null })])
		],
		['collectionLog', (api) => api.collectionLog(ID), `/api/v1/collections/${ID}/log`, page],
		[
			'search',
			(api) =>
				api.search('heliophysics', {
					q: 'solar wind',
					labels: ['mission=ace', 'level=l2'],
					states: ['active', 'draft'],
					cursor: 'c',
					limit: 25
				}),
			'/api/v1/catalogs/heliophysics/search?q=solar+wind&label=mission%3Dace&label=level%3Dl2&state=active&state=draft&cursor=c&limit=25',
			page
		],
		['schema', (api) => api.schema(ID), `/api/v1/schemas/${ID}`, schemaFixture()]
	])('%s calls the documented URL and decodes the answer', async (_, call, path, body) => {
		const { api, calls } = client([jsonResponse(body)]);
		expect(await call(api)).toEqual(body);
		expect(calls.map(({ url }) => url)).toEqual([`${BASE}${path}`]);
	});

	it('leaves out empty queries and cursors', async () => {
		const { api, calls } = client([jsonResponse(pageFixture([]))]);
		await api.search('heliophysics', { q: '', cursor: null });
		expect(calls[0].url).toBe(`${BASE}/api/v1/catalogs/heliophysics/search`);
	});

	it('encodes every path segment', async () => {
		const { api, calls } = client([jsonResponse(organizationFixture())]);
		await api.organization('a b?c#d;é');
		expect(calls[0].url).toBe(`${BASE}/api/v1/organizations/a%20b%3Fc%23d%3B%C3%A9`);
	});

	it.each(['', '.', '..', 'heliophysics/grants', '/', 'a\\b', '%2e%2e', 'a%2Fb', '%'])(
		'refuses the path segment %j without calling the API',
		async (segment) => {
			const { api, calls } = client([jsonResponse({})]);
			const error = await failure(api.catalog(segment));
			expect(error).toMatchObject({ status: 400, code: 'INVALID_SEGMENT' });
			expect(calls).toHaveLength(0);
		}
	);

	it.each<[string, (api: HuronApi) => Promise<unknown>]>([
		['namespace', (api) => api.namespace('heliophysics', 'solar-wind/../grants')],
		['collectionByIdentifier', (api) => api.collectionByIdentifier('heliophysics', 'a/b')],
		['collection', (api) => api.collection(`${ID}/log`)],
		['collectionSidecar', (api) => api.collectionSidecar(`${ID}/metadata.json`)],
		['search', (api) => api.search('heliophysics/grants', { q: 'wind' })]
	])('refuses a segment with a slash in %s as a rejected promise', async (_, call) => {
		const { api, calls } = client([jsonResponse({})]);
		expect(await failure(call(api))).toMatchObject({ status: 400, code: 'INVALID_SEGMENT' });
		expect(calls).toHaveLength(0);
	});
});

describe('HuronApi requests', () => {
	it('sends the bearer token with the global fetch options and no cookies', async () => {
		const { api, calls } = client([jsonResponse(whoamiFixture())]);
		await api.whoami();
		const init = calls[0].init;
		const headers = new Headers(init?.headers);
		expect(headers.get('authorization')).toBe(`Bearer ${TOKEN}`);
		expect(headers.get('accept')).toBe('application/json');
		expect(headers.has('cookie')).toBe(false);
		expect(init).toMatchObject({ method: 'GET', credentials: 'omit', redirect: 'error' });
		expect(init?.signal).toBeInstanceOf(AbortSignal);
	});

	it('returns the sidecar text byte for byte', async () => {
		const text = '{\n  "title": "ACE"\n}\n';
		const { api, calls } = client([new Response(text, { status: 200 })]);
		expect(await api.collectionSidecar(ID)).toBe(text);
		expect(calls[0].url).toBe(`${BASE}/api/v1/collections/${ID}/metadata.json`);
	});

	it('memoizes GET answers by URL when asked to', async () => {
		const { api, calls } = client([jsonResponse(pageFixture([organizationFixture()]))], {
			memoize: true
		});
		const [first, second] = await Promise.all([
			api.organizations({ limit: 500 }),
			api.organizations({ limit: 500 })
		]);
		expect(first).toEqual(second);
		await api.organizations({ limit: 50 });
		expect(calls).toHaveLength(2);
	});

	it('calls again for every request without memoization', async () => {
		const { api, calls } = client([jsonResponse(whoamiFixture())]);
		await api.whoami();
		await api.whoami();
		expect(calls).toHaveLength(2);
	});

	it('never shares a request that has a signal of its own', async () => {
		const { api, calls } = client(
			[
				({ url }) =>
					url.includes('/search?')
						? jsonResponse(pageFixture([collectionFixture()]))
						: jsonResponse(collectionFixture())
			],
			{ memoize: true }
		);
		const { signal } = new AbortController();
		await api.search('heliophysics', { q: 'wind' }, { signal });
		await api.search('heliophysics', { q: 'wind' }, { signal });
		await api.search('heliophysics', { q: 'wind' });
		await api.search('heliophysics', { q: 'wind' });
		expect(calls).toHaveLength(3);
		await api.collectionByIdentifier('heliophysics', 'fields.run001', { signal });
		await api.collectionByIdentifier('heliophysics', 'fields.run001', { signal });
		expect(calls).toHaveLength(5);
	});

	it('parses lists, searches and collections without a reviver, whatever digits they hold', async () => {
		// An ordinary float (1/3 writes 16 digits) and a 16-digit run in a text both used to set
		// off the reviver that keeps int64 digits, over the whole answer.
		const metadata = { title: 'Run 1234567890123456', ratio: 1 / 3 };
		const rows = pageFixture([collectionFixture({ metadata })]);
		const { api } = client([
			({ url }) =>
				url.includes('/collections?') || url.includes('/search?')
					? jsonResponse(rows)
					: jsonResponse(collectionFixture({ metadata }))
		]);
		const parse = vi.spyOn(JSON, 'parse');
		try {
			await api.namespaceCollections('heliophysics', 'fields', { limit: 50 });
			await api.search('heliophysics', { q: 'run' });
			await api.collectionByIdentifier('heliophysics', 'fields.run001');
			await api.collection(ID);
			expect(parse).toHaveBeenCalledTimes(4);
			for (const args of parse.mock.calls) expect(args).toHaveLength(1);
		} finally {
			parse.mockRestore();
		}
	});

	it('keeps the digits of integers past 2^53 in schema documents and exact reads', async () => {
		const text =
			'{"type":"object","properties":{"n":{"type":"integer","maximum":9223372036854775807}}}';
		const answer = JSON.stringify(collectionFixture()).replace(
			'"schema_override":null',
			`"schema_override":${text}`
		);
		const { api } = client([
			({ url }) =>
				url.endsWith('/schema')
					? new Response(text, { headers: { 'content-type': 'application/json' } })
					: new Response(answer, { headers: { 'content-type': 'application/json' } })
		]);
		const maximum = (document: unknown) => {
			const properties = isRecord(document) ? document.properties : null;
			const n = isRecord(properties) ? properties.n : null;
			return isRecord(n) ? integerDigits(n, 'maximum') : null;
		};
		expect(maximum(await api.catalogSchema('heliophysics'))).toBe('9223372036854775807');
		expect(maximum(await api.collectionSchema(ID))).toBe('9223372036854775807');
		expect(maximum((await api.collection(ID, { exact: true })).schema_override)).toBe(
			'9223372036854775807'
		);
		expect(maximum((await api.collection(ID)).schema_override)).toBeNull();
	});

	it('never shares an answer between a plain read and an exact one', async () => {
		const { api, calls } = client([jsonResponse(collectionFixture())], { memoize: true });
		await api.collection(ID);
		await api.collection(ID);
		await api.collection(ID, { exact: true });
		await api.collection(ID, { exact: true });
		expect(calls).toHaveLength(2);
	});

	it('keeps the token out of every serialization', () => {
		const { api } = client([]);
		expect(JSON.stringify(api)).toBe('{}');
		expect(JSON.stringify(api)).not.toContain(TOKEN);
		expect(() => devalue.stringify({ api })).toThrow();
		expect(() => devalue.uneval({ api })).toThrow();
	});
});

describe('HuronApi failures', () => {
	it('reads problem documents into errors', async () => {
		const { api } = client([
			problemResponse(404, 'NOT_FOUND', { identifier: 'x' }, 'no such catalog')
		]);
		const error = await failure(api.catalog('nope'));
		expect(error).toMatchObject({
			status: 404,
			code: 'NOT_FOUND',
			title: 'NOT_FOUND',
			detail: 'no such catalog',
			context: { identifier: 'x' }
		});
		expect(error.requestId).toBeUndefined();
		expect(error.message).not.toContain('no such catalog');
	});

	it('takes the request id of internal errors from the context', async () => {
		const { api } = client([problemResponse(500, 'INTERNAL', { request_id: 'req-42' })]);
		expect((await failure(api.whoami())).requestId).toBe('req-42');
	});

	it.each([
		[
			'an HTML page',
			new Response('<h1>Bad gateway</h1>', {
				status: 502,
				headers: { 'content-type': 'text/html' }
			})
		],
		['plain JSON', jsonResponse({ code: 'NOT_FOUND' }, 404)],
		['an empty answer', new Response(null, { status: 401 })]
	])('gives the code HTTP to %s', async (_, response) => {
		const { api } = client([response]);
		const error = await failure(api.whoami());
		expect(error.code).toBe('HTTP');
		expect(error.status).toBe(response.status);
	});

	it.each([
		['invalid JSON', new Response('{', { status: 200 })],
		['a missing field', jsonResponse({ subject: 's', name: 'n', groups: [] })],
		['a wrongly typed field', jsonResponse({ ...whoamiFixture(), groups: 'g' })]
	])('treats %s as a malformed answer', async (_, response) => {
		const { api } = client([response]);
		expect(await failure(api.whoami())).toMatchObject({ status: 502, code: 'HTTP' });
	});

	it('reports network failures as an unreachable API', async () => {
		const { api, calls } = client([new TypeError('fetch failed')]);
		expect(await failure(api.whoami())).toMatchObject({ status: 503, code: 'API_UNREACHABLE' });
		expect(calls).toHaveLength(1);
	});

	it('gives up after the timeout', async () => {
		const { api } = client([hangingAnswer], { timeoutMs: 20 });
		expect(await failure(api.whoami())).toMatchObject({ status: 503, code: 'API_UNREACHABLE' });
	});

	it('gives up when its caller aborts, before the timeout', async () => {
		const { api, calls } = client([hangingAnswer], { timeoutMs: 60_000 });
		const caller = new AbortController();
		const searching = failure(api.search('heliophysics', { q: 'wind' }, { signal: caller.signal }));
		const lookup = failure(
			api.collectionByIdentifier('heliophysics', 'fields.run001', { signal: caller.signal })
		);
		caller.abort();
		expect(await searching).toMatchObject({ status: 503, code: 'API_UNREACHABLE' });
		expect(await lookup).toMatchObject({ status: 503, code: 'API_UNREACHABLE' });
		expect(calls.map(({ init }) => init?.signal?.aborted)).toEqual([true, true]);
	});

	it('never retries a request its caller aborted', async () => {
		const { api, calls } = client([connectionReset(), jsonResponse(pageFixture([]))]);
		const caller = new AbortController();
		caller.abort();
		expect(await failure(api.search('heliophysics', {}, { signal: caller.signal }))).toMatchObject({
			status: 503,
			code: 'API_UNREACHABLE'
		});
		expect(calls).toHaveLength(1);
	});

	it.each(['ECONNRESET', 'UND_ERR_SOCKET', 'EPIPE'])(
		'retries a GET once after a %s',
		async (code) => {
			const { api, calls } = client([connectionReset(code), jsonResponse(whoamiFixture())]);
			expect(await api.whoami()).toEqual(whoamiFixture());
			expect(calls).toHaveLength(2);
		}
	);

	it('stops reading an answer once it holds more than its ceiling, and fails it as too large', async () => {
		// A list carries each collection whole: metadata, problems and an override of any size.
		let pulled = 0;
		const endless = () =>
			new Response(
				new ReadableStream<Uint8Array>({
					pull(controller) {
						pulled += 1;
						controller.enqueue(new Uint8Array(1024).fill(0x20));
					}
				}),
				{ headers: { 'content-type': 'application/json' } }
			);
		const { api } = client([endless], { maxAnswerBytes: 10 * 1024 });
		expect(await failure(api.namespaceCollections('heliophysics', 'fields'))).toMatchObject({
			status: 502,
			code: 'HTTP',
			title: 'API answer too large'
		});
		expect(pulled).toBeLessThanOrEqual(12);
	});

	it('refuses an answer whose declared length is over its ceiling without reading it', async () => {
		let pulled = 0;
		const declared = new Response(
			new ReadableStream<Uint8Array>({
				pull(controller) {
					pulled += 1;
					controller.enqueue(new Uint8Array(1024));
				}
			}),
			{ headers: { 'content-type': 'application/json', 'content-length': '20000' } }
		);
		const { api } = client([() => declared], { maxAnswerBytes: 10_000 });
		expect(await failure(api.collectionSidecar(ID))).toMatchObject({
			status: 502,
			title: 'API answer too large'
		});
		expect(pulled).toBeLessThanOrEqual(1);
	});

	it('reads an answer of exactly its ceiling, whatever its chunks split', async () => {
		// "é" is two bytes: chunks of one byte split each in two.
		const text = JSON.stringify({ items: [], next_cursor: 'é'.repeat(10) });
		const bytes = new TextEncoder().encode(text);
		const chunked = () =>
			new Response(
				new ReadableStream<Uint8Array>({
					start(controller) {
						for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
						controller.close();
					}
				}),
				{ headers: { 'content-type': 'application/json' } }
			);
		const { api } = client([chunked], { maxAnswerBytes: bytes.byteLength });
		expect((await api.namespaces('heliophysics', '')).next_cursor).toBe('é'.repeat(10));
	});

	it('retries only once', async () => {
		const { api, calls } = client([connectionReset(), connectionReset(), jsonResponse({})]);
		expect(await failure(api.whoami())).toMatchObject({ status: 503, code: 'API_UNREACHABLE' });
		expect(calls).toHaveLength(2);
	});
});

describe('exchange', () => {
	const answer = {
		huron_token: 'huron-token',
		token_type: 'Bearer',
		expires_at: '2026-10-29T18:00:00Z',
		subject: 'sub-erin',
		name: 'Erin Example',
		groups: ['helio-readers']
	};

	it('posts the company token and decodes the answer', async () => {
		const { fetch, calls } = fakeFetch(jsonResponse(answer));
		const result = await exchange('company-id-token', { baseUrl: BASE, fetch, timeoutMs: 1000 });
		expect(result).toEqual({
			huron_token: 'huron-token',
			expires_at: '2026-10-29T18:00:00Z',
			subject: 'sub-erin',
			name: 'Erin Example',
			groups: ['helio-readers']
		});
		expect(calls[0].url).toBe(`${BASE}/api/v1/auth/exchange`);
		expect(calls[0].init).toMatchObject({ method: 'POST', credentials: 'omit', redirect: 'error' });
		expect(calls[0].init?.body).toBe(JSON.stringify({ company_token: 'company-id-token' }));
		expect(new Headers(calls[0].init?.headers).get('content-type')).toBe('application/json');
	});

	it('reports rejections with their status and code', async () => {
		const { fetch } = fakeFetch(problemResponse(503, 'GROUP_DIRECTORY_UNAVAILABLE'));
		const error = await failure(exchange('t', { baseUrl: BASE, fetch, timeoutMs: 1000 }));
		expect(error).toMatchObject({ status: 503, code: 'GROUP_DIRECTORY_UNAVAILABLE' });
	});

	it('never retries the exchange', async () => {
		const { fetch, calls } = fakeFetch(connectionReset(), jsonResponse(answer));
		const error = await failure(exchange('t', { baseUrl: BASE, fetch, timeoutMs: 1000 }));
		expect(error.code).toBe('API_UNREACHABLE');
		expect(calls).toHaveLength(1);
	});
});
