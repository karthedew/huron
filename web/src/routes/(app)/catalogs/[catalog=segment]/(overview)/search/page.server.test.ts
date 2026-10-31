// @vitest-environment node
import { isHttpError, isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Collection } from '$api/types';
import { searchResult } from '$lib/search';
import { sessionStore } from '$lib/server/sessions';
import {
	catalogFixture,
	collectionFixture,
	fakeApi,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse,
	TEST_API,
	whoamiFixture,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { catalogRole } from '$lib/testing/catalog-data';
import { parsedObject } from '$lib/testing/json';
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

const MAG = collectionFixture({
	id: 'c-mag',
	identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
	metadata: {
		title: 'ACE MAG level 2, 2024',
		labels: { mission: 'ace', level: 'l2' }
	}
});
const SWEPAM = collectionFixture({
	id: 'c-swepam',
	identifier: 'heliophysics.solar-wind.ace.swepam-2024',
	name: 'swepam-2024',
	metadata: { title: 'ACE SWEPAM 2024', labels: { mission: 'ace' } }
});
const DRAFT = collectionFixture({
	id: 'c-draft',
	identifier: 'heliophysics.solar-wind.ace.mag-l1-draft',
	name: 'mag-l1-draft',
	state: 'draft',
	path: null,
	metadata: { title: 'ACE MAG level 1 (draft)' }
});

const SEARCH = '/catalogs/heliophysics/search';
const BY_IDENTIFIER = '/catalogs/heliophysics/collections';

function searchEvent(query = '') {
	return signedInLoadEvent({
		url: `http://localhost:4173/catalogs/heliophysics/search${query}`,
		routeId: '/(app)/catalogs/[catalog=segment]/(overview)/search',
		params: { catalog: 'heliophysics' }
	});
}

function stub(routes: Record<string, FetchAnswer>) {
	const api = fakeApi(routes);
	vi.stubGlobal('fetch', api.fetch);
	return api;
}

/** What `maySeeDrafts` reads for a user with these roles on the fixture catalog. */
function viewer(roles: string[]): Record<string, FetchAnswer> {
	return {
		'/catalogs/heliophysics': jsonResponse(catalogFixture()),
		'/organizations?limit=500': jsonResponse(pageFixture([organizationFixture()])),
		'/auth/whoami': jsonResponse(whoamiFixture({ roles: roles.map(catalogRole) }))
	};
}

async function outcomeOf(promise: Promise<unknown>): Promise<unknown> {
	return promise.catch((thrown: unknown) => thrown);
}

describe('/catalogs/[catalog]/search load', () => {
	it('searches with the query of the address and returns the results as plain rows', async () => {
		const api = stub({
			[`${SEARCH}?q=ace&label=mission%3Dace&limit=25`]: jsonResponse(
				pageFixture([MAG, SWEPAM], 'next-page')
			)
		});
		const data = await load(searchEvent('?q=ace&label=mission%3Dace').event);
		expect(data).toEqual({
			search: {
				q: 'ace',
				labels: [{ key: 'mission', value: 'ace' }],
				states: null,
				cursor: null
			},
			errors: { q: null, label: null, form: null },
			pendingLabel: '',
			exact: null,
			results: [searchResult(MAG), searchResult(SWEPAM)],
			nextCursor: 'next-page'
		});
		// The text names no collection, so nothing is looked up; nor are the user's roles.
		expect(api.calls).toHaveLength(1);
	});

	it('searches everything for the empty query, a page at a time', async () => {
		const api = stub({
			[`${SEARCH}?limit=25`]: jsonResponse(pageFixture([MAG], 'c2')),
			[`${SEARCH}?cursor=c2&limit=25`]: jsonResponse(pageFixture([SWEPAM]))
		});
		expect((await load(searchEvent().event)).results).toEqual([searchResult(MAG)]);
		const later = await load(searchEvent('?cursor=c2').event);
		expect(later.results).toEqual([searchResult(SWEPAM)]);
		expect(later.nextCursor).toBeNull();
		expect(api.calls).toHaveLength(2);
	});

	it('reads the browser’s own encoding of the form as the same search', async () => {
		const api = stub({
			[`${SEARCH}?q=solar+wind&label=level%3Dl2&limit=25`]: jsonResponse(pageFixture([MAG]))
		});
		const data = await load(
			searchEvent('?q=+solar+wind+&label=level%3Dl2&label=&state=active&state=incomplete').event
		);
		expect(data.search).toEqual({
			q: 'solar wind',
			labels: [{ key: 'level', value: 'l2' }],
			states: null,
			cursor: null
		});
		expect(api.calls).toHaveLength(1);
	});

	it('shows a text too long for the API at its field, without calling it', async () => {
		const api = stub({});
		const data = await load(searchEvent(`?q=${'w'.repeat(201)}&label=mission%3Dace`).event);
		expect(data.errors).toEqual({
			q: 'Use at most 200 characters; this text has 201.',
			label: null,
			form: null
		});
		expect(data.search.q).toBe('w'.repeat(201));
		expect(data.search.labels).toEqual([{ key: 'mission', value: 'ace' }]);
		expect(data.results).toBeNull();
		expect(data.exact).toBeNull();
		expect(api.calls).toHaveLength(0);
	});

	it('shows a label it cannot read at the field for adding one, without calling the API', async () => {
		const api = stub({});
		const data = await load(searchEvent('?q=wind&label=mission&label=level%3Dl2').event);
		expect(data.errors.label).toBe('Write a label filter as key=value, for example mission=ace.');
		expect(data.pendingLabel).toBe('mission');
		expect(data.search.labels).toEqual([{ key: 'level', value: 'l2' }]);
		expect(data.results).toBeNull();
		expect(api.calls).toHaveLength(0);
	});

	it('shows a label filter longer than a chip searches for at its field, without calling the API', async () => {
		// One contributor's long label must not make a link that repeats it in every row's chips.
		const api = stub({});
		const long = `zz=${'y'.repeat(8000)}`;
		const data = await load(
			searchEvent(`?q=amp&label=mission%3Dace&label=${encodeURIComponent(long)}`).event
		);
		expect(data.errors.label).toBe(
			"Use at most 100 characters in a label filter's key and in its value."
		);
		expect(data.pendingLabel).toBe(long);
		expect(data.search.labels).toEqual([{ key: 'mission', value: 'ace' }]);
		expect(data.results).toBeNull();
		expect(api.calls).toHaveLength(0);
	});

	it('shows more label filters than a search may have at the field, without calling the API', async () => {
		const api = stub({});
		const labels = Array.from({ length: 120 }, (_, index) => `label=k${index}%3Dv`).join('&');
		const data = await load(searchEvent(`?q=wind&${labels}`).event);
		expect(data.errors.label).toBe('Use at most 10 label filters; this search has 120.');
		expect(data.search.labels).toHaveLength(10);
		expect(data.results).toBeNull();
		expect(api.calls).toHaveLength(0);
	});

	it('reads a label with a line break that the form kept as JSON', async () => {
		const api = stub({
			[`${SEARCH}?q=nn&label=nl%3Da%0Ab&limit=25`]: jsonResponse(pageFixture([MAG]))
		});
		const query = new URLSearchParams([
			['q', 'nn'],
			['label_json', JSON.stringify('nl=a\nb')],
			['label', ''],
			['state', 'active'],
			['state', 'incomplete']
		]);
		const data = await load(searchEvent(`?${query}`).event);
		expect(data.search.labels).toEqual([{ key: 'nl', value: 'a\nb' }]);
		expect(data.results).toEqual([searchResult(MAG)]);
		expect(api.calls).toHaveLength(1);
	});

	it('finds nothing, without asking the API, where labels give one key two values', async () => {
		const api = stub({});
		const data = await load(
			searchEvent(
				`?q=${encodeURIComponent('solar-wind.ace.mag-l2-2024')}&label=mission%3Dace&label=mission%3Dwind`
			).event
		);
		expect(data.errors).toEqual({ q: null, label: null, form: null });
		expect(data.search.labels).toEqual([
			{ key: 'mission', value: 'ace' },
			{ key: 'mission', value: 'wind' }
		]);
		expect(data.results).toEqual([]);
		expect(data.exact).toBeNull();
		expect(data.nextCursor).toBeNull();
		expect(api.calls).toHaveLength(0);
	});

	it('includes drafts for a user who may create collections in the catalog', async () => {
		const api = stub({
			...viewer(['contributor']),
			[`${SEARCH}?q=ace&state=active&state=draft&limit=25`]: jsonResponse(pageFixture([DRAFT, MAG]))
		});
		const data = await load(searchEvent('?q=ace&state=draft&state=active').event);
		expect(data.search.states).toEqual(['active', 'draft']);
		expect(data.results).toEqual([searchResult(DRAFT), searchResult(MAG)]);
		// The roles and the organization's id, then the search itself.
		expect(api.calls.map(({ url }) => url.slice(TEST_API.length)).sort()).toEqual([
			'/auth/whoami',
			'/catalogs/heliophysics',
			`${SEARCH}?q=ace&state=active&state=draft&limit=25`,
			'/organizations?limit=500'
		]);
	});

	it('ignores drafts for a reader and never sends them', async () => {
		const api = stub({
			...viewer(['reader']),
			[`${SEARCH}?q=ace&limit=25`]: jsonResponse(pageFixture([MAG])),
			[`${SEARCH}?q=ace&state=incomplete&limit=25`]: jsonResponse(pageFixture([]))
		});
		const only = await load(searchEvent('?q=ace&state=draft').event);
		expect(only.search.states).toBeNull();
		expect(only.results).toEqual([searchResult(MAG)]);
		const mixed = await load(searchEvent('?q=ace&state=draft&state=incomplete').event);
		expect(mixed.search.states).toEqual(['incomplete']);
		expect(api.calls.some(({ url }) => url.includes('state=draft'))).toBe(false);
	});

	it('takes a user whose roles it cannot read as a reader, logging why', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		stub({
			...viewer(['contributor']),
			'/auth/whoami': problemResponse(503, 'DEPENDENCY_UNAVAILABLE'),
			[`${SEARCH}?limit=25`]: jsonResponse(pageFixture([MAG]))
		});
		const data = await load(searchEvent('?state=draft').event);
		expect(data.search.states).toBeNull();
		expect(data.results).toEqual([searchResult(MAG)]);
		expect(log).toHaveBeenCalledOnce();
	});

	it.each([
		[{ problems: [{ path: '/query/q', message: 'too long', rule: 'string_too_long' }] }, 'q'],
		[{ label: 'mission' }, 'label'],
		[{ problems: [{ path: '/query/label/0', message: 'bad', rule: 'x' }] }, 'label'],
		[{ problems: [{ path: '/query/limit', message: 'bad', rule: 'x' }] }, 'form'],
		[{}, 'form']
	] as const)('shows a refusal of the API (%j) inline, at %s', async (context, field) => {
		stub({ [`${SEARCH}?q=wind&limit=25`]: problemResponse(422, 'REQUEST_INVALID', context) });
		const data = await load(searchEvent('?q=wind').event);
		expect(data.results).toBeNull();
		expect(data.errors).toEqual({
			q: field === 'q' ? "The Huron service didn't accept this text." : null,
			label: field === 'label' ? "The Huron service didn't accept these label filters." : null,
			form: field === 'form' ? "The Huron service didn't accept this search." : null
		});
		expect(JSON.stringify(data)).not.toContain('the API explains');
	});

	it('shows the other failures of the search as their pages', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		for (const [status, code] of [
			[404, 'NOT_FOUND'],
			[403, 'FORBIDDEN'],
			[503, 'DEPENDENCY_UNAVAILABLE'],
			[500, 'INTERNAL']
		] as const) {
			stub({ [`${SEARCH}?q=wind&limit=25`]: problemResponse(status, code) });
			const outcome = await outcomeOf(load(searchEvent('?q=wind').event));
			expect(isHttpError(outcome, status)).toBe(true);
		}
	});

	it('restarts at the first page when the cursor is no longer accepted', async () => {
		stub({
			[`${SEARCH}?q=run&cursor=stale&limit=25`]: problemResponse(400, 'INVALID_CURSOR')
		});
		const outcome = await outcomeOf(load(searchEvent('?q=run&cursor=stale').event));
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/catalogs/heliophysics/search?q=run&notice=page_expired'
		);
	});

	it('ends the session when the API no longer accepts the token', async () => {
		stub({ [`${SEARCH}?q=wind&limit=25`]: problemResponse(401, 'TOKEN_INVALID') });
		const { event, sessionId } = searchEvent('?q=wind');
		const outcome = await outcomeOf(load(event));
		expect(isRedirect(outcome) && outcome.location).toBe(
			'/login?status=expired&returnTo=%2Fcatalogs%2Fheliophysics%2Fsearch%3Fq%3Dwind'
		);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it('returns page data SvelteKit can send, whatever keys the metadata holds', async () => {
		const proto = collectionFixture({
			id: 'c-proto',
			identifier: 'heliophysics.solar-wind.ace.proto',
			metadata: parsedObject(
				'{"title":"Proto","__proto__":{"polluted":true},"labels":{"__proto__":"x","mission":"proto"}}'
			)
		});
		stub({
			[`${SEARCH}?label=__proto__%3Dx&limit=25`]: jsonResponse(pageFixture([proto]))
		});
		const data = await load(searchEvent('?label=__proto__%3Dx').event);
		expect(() => serializePageData(data)).not.toThrow();
		expect(data.results).toEqual([searchResult(proto)]);
		expect(data.results?.[0].labels.map(({ key }) => key)).toEqual(['__proto__', 'mission']);
	});

	it('returns small page data, however long the metadata of the results is', async () => {
		// Metadata may take up a mebibyte: one contributor's labels must not make every reader's page.
		const mebibyte = 'n'.repeat(1024 * 1024);
		const huge = Array.from({ length: 3 }, (_, index) =>
			collectionFixture({
				id: `c-huge-${index}`,
				identifier: `heliophysics.empty.huge-${index}`,
				metadata: {
					title: mebibyte,
					description: mebibyte,
					labels: { note: mebibyte, [mebibyte]: 'key', mission: 'ace' }
				}
			})
		);
		stub({ [`${SEARCH}?limit=25`]: jsonResponse(pageFixture(huge)) });
		const data = await load(searchEvent().event);
		expect(data.results).toHaveLength(3);
		for (const sent of serializePageData(data)) expect(sent.length).toBeLessThan(10_000);
	});
});

describe('the exact match of the catalog search', () => {
	const NAMED = 'solar-wind.ace.mag-l2-2024';

	/** A search for `text`, which names MAG, and its answers: a page of results and the lookup. */
	function exact(text: string, lookup: FetchAnswer, results: Collection[] = [MAG, SWEPAM]) {
		return stub({
			[searchPath(text)]: jsonResponse(pageFixture(results)),
			[`${BY_IDENTIFIER}/${NAMED}`]: lookup
		});
	}

	it.each([`heliophysics.${NAMED}`, NAMED, '  Heliophysics.Solar-Wind.ACE.Mag-L2-2024 '])(
		'comes first for %j, and not again among the results',
		async (text) => {
			const api = exact(text.trim(), jsonResponse(MAG));
			const data = await load(searchEvent(`?q=${encodeURIComponent(text)}`).event);
			expect(data.exact).toEqual(searchResult(MAG));
			expect(data.results).toEqual([searchResult(SWEPAM)]);
			expect(api.calls).toHaveLength(2);
		}
	);

	it('shows even when it is beyond the first page of results', async () => {
		exact(NAMED, jsonResponse(MAG), [SWEPAM]);
		const data = await load(searchEvent(`?q=${NAMED}`).event);
		expect(data.exact).toEqual(searchResult(MAG));
		expect(data.results).toEqual([searchResult(SWEPAM)]);
	});

	it('is looked up on the first page only, and left out of the list on every page', async () => {
		// The first page showed it at its top: a later page holding it does not repeat it.
		const api = stub({
			[`${SEARCH}?q=${NAMED}&cursor=c2&limit=25`]: jsonResponse(pageFixture([SWEPAM, MAG]))
		});
		const data = await load(searchEvent(`?q=${NAMED}&cursor=c2`).event);
		expect(data.exact).toBeNull();
		expect(data.results).toEqual([searchResult(SWEPAM)]);
		expect(api.calls).toHaveLength(1);
		// Named as a full identifier, in any case, the same.
		stub({
			[`${SEARCH}?q=Heliophysics.${NAMED}&cursor=c2&limit=25`]: jsonResponse(pageFixture([MAG]))
		});
		const full = await load(searchEvent(`?q=Heliophysics.${NAMED}&cursor=c2`).event);
		expect(full.results).toEqual([]);
		// A text that names no collection takes nothing out.
		stub({ [`${SEARCH}?q=mag&cursor=c2&limit=25`]: jsonResponse(pageFixture([MAG])) });
		expect((await load(searchEvent('?q=mag&cursor=c2').event)).results).toEqual([
			searchResult(MAG)
		]);
	});

	it('stays in the list of the first page when its lookup failed', async () => {
		vi.spyOn(console, 'error').mockImplementation(() => undefined);
		exact(NAMED, problemResponse(503, 'DEPENDENCY_UNAVAILABLE'), [SWEPAM, MAG]);
		const data = await load(searchEvent(`?q=${NAMED}`).event);
		expect(data.exact).toBeNull();
		expect(data.results).toEqual([searchResult(SWEPAM), searchResult(MAG)]);
	});

	it.each([
		[403, 'FORBIDDEN'],
		[404, 'NOT_FOUND'],
		[400, 'INVALID_SEGMENT']
	] as const)(
		'shows nothing, and logs nothing, when the lookup answers %i',
		async (status, code) => {
			const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
			exact(NAMED, problemResponse(status, code));
			const data = await load(searchEvent(`?q=${NAMED}`).event);
			expect(data.exact).toBeNull();
			expect(data.results).toEqual([searchResult(MAG), searchResult(SWEPAM)]);
			expect(log).not.toHaveBeenCalled();
		}
	);

	it('still shows the results when the lookup fails, and logs it', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		exact(NAMED, problemResponse(503, 'DEPENDENCY_UNAVAILABLE'));
		const data = await load(searchEvent(`?q=${NAMED}`).event);
		expect(data.exact).toBeNull();
		expect(data.results).toEqual([searchResult(MAG), searchResult(SWEPAM)]);
		expect(log).toHaveBeenCalledOnce();
	});

	it('ends the session when the lookup meets an expired token', async () => {
		exact(NAMED, problemResponse(401, 'TOKEN_INVALID'));
		const { event, sessionId } = searchEvent(`?q=${NAMED}`);
		const outcome = await outcomeOf(load(event));
		expect(isRedirect(outcome) && outcome.location).toBe(
			`/login?status=expired&returnTo=${encodeURIComponent(`/catalogs/heliophysics/search?q=${NAMED}`)}`
		);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it("honors the search's filters, as the result whose identifier is the text", async () => {
		const text = 'solar-wind.ace.mag-l1-draft';
		const api = stub({
			...viewer(['contributor']),
			[searchPath(text)]: jsonResponse(pageFixture([])),
			[searchPath(text, '&state=draft')]: jsonResponse(pageFixture([DRAFT])),
			[searchPath(text, '&label=mission%3Dace&state=draft')]: jsonResponse(pageFixture([])),
			[`${BY_IDENTIFIER}/${text}`]: jsonResponse(DRAFT)
		});
		// The default states hold no drafts, even for a contributor who may see this one.
		expect((await load(searchEvent(`?q=${text}`).event)).exact).toBeNull();
		const drafts = await load(searchEvent(`?q=${text}&state=draft`).event);
		expect(drafts.exact).toEqual(searchResult(DRAFT));
		expect(drafts.results).toEqual([]);
		// Nor does it show without a label a filter asks for.
		const labelled = await load(searchEvent(`?q=${text}&label=mission%3Dace&state=draft`).event);
		expect(labelled.exact).toBeNull();
		expect(api.calls.filter(({ url }) => url.includes(BY_IDENTIFIER))).toHaveLength(3);
	});

	it('looks nothing up for a text that names no collection of this catalog', async () => {
		for (const text of ['wind', 'heliophysics.fields', 'a/b.c', 'fields.run%001', 'x.y z']) {
			const api = stub({ [searchPath(text)]: jsonResponse(pageFixture([])) });
			const data = await load(searchEvent(`?q=${encodeURIComponent(text)}`).event);
			expect(data.exact).toBeNull();
			expect(api.calls, text).toHaveLength(1);
		}
	});
});

/** The API's search for a text, as the client writes it: the text, then `more`, then the limit. */
function searchPath(text: string, more = ''): string {
	return `${SEARCH}?${new URLSearchParams({ q: text })}${more}&limit=25`;
}
