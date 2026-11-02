// @vitest-environment node
import { isRedirect } from '@sveltejs/kit';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Catalog, Collection, RoleGrant } from '$api/types';
import { emptySearch, searchResult, type Search } from '$lib/search';
import {
	catalogFixture,
	collectionFixture,
	fakeApi,
	hangingAnswer,
	jsonResponse,
	organizationFixture,
	pageFixture,
	problemResponse,
	type FetchAnswer
} from '$lib/testing/api-fixtures';
import { signedInLoadEvent } from '$lib/testing/sessions';
import { api } from './guard';
import {
	CONCURRENCY,
	DEADLINE_MS,
	fanOut,
	organizationCatalogs,
	searchOrganization,
	type Settlement
} from './org-search';
import type { DraftAccess } from './search';
import { sessionStore } from './sessions';

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
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	globalThis.huronWebSessions?.stop();
	globalThis.huronWebSessions = undefined;
});

const HELIO = organizationFixture();
const HELIOPHYSICS = catalogFixture();
const SPACE_WEATHER = catalogFixture({
	id: '0192f2a4-0000-7000-8000-000000000102',
	name: 'space-weather',
	display_name: 'Space Weather'
});
const MAG = collectionFixture({
	id: 'c-mag',
	identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
	metadata: { title: 'ACE MAG level 2, 2024', labels: { mission: 'ace' } }
});
const SWEPAM = collectionFixture({
	id: 'c-swepam',
	identifier: 'heliophysics.solar-wind.ace.swepam-2024',
	name: 'swepam-2024',
	metadata: { title: 'ACE SWEPAM 2024' }
});
const KP = collectionFixture({
	id: 'c-kp',
	identifier: 'space-weather.alerts.kp-index-2024',
	catalog: 'space-weather',
	namespace: 'alerts',
	name: 'kp-index-2024',
	metadata: { title: 'Kp index 2024' }
});

/** A reader of every catalog: no drafts anywhere. */
const READER: DraftAccess = { roles: [], organizations: [HELIO] };

/** Someone who may create collections in heliophysics alone. */
const CONTRIBUTOR: DraftAccess = {
	roles: [{ scope: 'catalog', scope_id: HELIOPHYSICS.id, role: 'contributor' }],
	organizations: [HELIO]
};

function searchFor(overrides: Partial<Search> = {}): Search {
	return { ...emptySearch(), ...overrides };
}

/** The `n`th made-up catalog of the organization. */
function numbered(n: number): Catalog {
	const name = `c${String(n).padStart(2, '0')}`;
	return catalogFixture({ id: `catalog-${n}`, name, display_name: `Catalog ${n}` });
}

/** The API path of a catalog's search, as the organization's search asks it. */
function searchPath(catalog: string, query = 'q=wind'): string {
	return `/catalogs/${catalog}/search?${query === '' ? '' : `${query}&`}limit=5`;
}

function orgSearchEvent() {
	return signedInLoadEvent({
		url: 'http://localhost:4173/orgs/helio/search?q=wind',
		routeId: '/(app)/orgs/[org=segment]/search',
		params: { org: 'helio' }
	});
}

function stub(routes: Record<string, FetchAnswer>) {
	const fake = fakeApi(routes);
	vi.stubGlobal('fetch', fake.fetch);
	return fake;
}

function search(catalogs: readonly Catalog[], searched: Search, access: DraftAccess = READER) {
	const { event } = orgSearchEvent();
	return searchOrganization(event, api(event), { search: searched, catalogs, access });
}

/** A promise and the functions that settle it, for tasks the test settles itself. */
function deferred<T>() {
	let resolve: (value: T) => void = () => undefined;
	let reject: (reason: unknown) => void = () => undefined;
	const promise = new Promise<T>((settle, fail) => {
		resolve = settle;
		reject = fail;
	});
	return { promise, resolve, reject };
}

describe('fanOut', () => {
	it("runs every task, at most `concurrency` at once, and settles in the items' order", async () => {
		const tasks = Array.from({ length: 7 }, () => deferred<string>());
		let running = 0;
		let most = 0;
		const started: number[] = [];
		const settled = fanOut(
			tasks.map((_, index) => index),
			async (index) => {
				started.push(index);
				running += 1;
				most = Math.max(most, running);
				try {
					return await tasks[index].promise;
				} finally {
					running -= 1;
				}
			},
			{ concurrency: 3, signal: new AbortController().signal }
		);
		expect(started).toEqual([0, 1, 2]);
		// Settled out of order; the next task starts as soon as one settles.
		tasks[2].resolve('c');
		await vi.waitFor(() => expect(started).toEqual([0, 1, 2, 3]));
		tasks[0].reject(new Error('down'));
		await vi.waitFor(() => expect(started).toHaveLength(5));
		for (const [index, task] of tasks.entries()) task.resolve(`v${index}`);
		const settlements = await settled;
		expect(most).toBe(3);
		expect(settlements).toEqual([
			{ status: 'failed', failure: new Error('down') },
			{ status: 'answered', value: 'v1' },
			{ status: 'answered', value: 'c' },
			...[3, 4, 5, 6].map((index) => ({ status: 'answered', value: `v${index}` }))
		]);
	});

	it('calls every task late that has not settled when the signal aborts, started or not', async () => {
		const deadline = new AbortController();
		const signals: AbortSignal[] = [];
		const quick = deferred<string>();
		const settled = fanOut(
			['quick', 'slow', 'waiting'],
			(item, signal) => {
				signals.push(signal);
				return item === 'quick' ? quick.promise : new Promise<string>(() => undefined);
			},
			{ concurrency: 2, signal: deadline.signal }
		);
		quick.resolve('in time');
		await vi.waitFor(() => expect(signals).toHaveLength(2));
		// 'waiting' started once 'quick' settled; nothing has settled since.
		deadline.abort();
		expect(await settled).toEqual([
			{ status: 'answered', value: 'in time' },
			{ status: 'late' },
			{ status: 'late' }
		]);
		expect(signals.every((signal) => signal.aborted)).toBe(true);
	});

	it('ignores what a task does once the fan-out is over, failures included', async () => {
		const deadline = new AbortController();
		const late = deferred<string>();
		const failing = deferred<string>();
		const settled = fanOut([late, failing], (task) => task.promise, {
			concurrency: 2,
			signal: deadline.signal
		});
		deadline.abort();
		const settlements: Array<Settlement<string>> = await settled;
		late.resolve('too late');
		failing.reject(new Error('after the deadline'));
		await new Promise((resolve) => setImmediate(resolve));
		expect(settlements).toEqual([{ status: 'late' }, { status: 'late' }]);
	});

	it('settles a task that throws before its first await as failed', async () => {
		const settlements = await fanOut(
			['ok', 'broken'],
			async (item) => {
				if (item === 'broken') throw new TypeError('bug');
				return item;
			},
			{ concurrency: 1, signal: new AbortController().signal }
		);
		expect(settlements).toEqual([
			{ status: 'answered', value: 'ok' },
			{ status: 'failed', failure: new TypeError('bug') }
		]);
	});

	it('settles nothing for no items, and every item late once the signal has aborted', async () => {
		const task = vi.fn(async () => 'never');
		expect(
			await fanOut([], task, { concurrency: 4, signal: new AbortController().signal })
		).toEqual([]);
		expect(await fanOut([1, 2], task, { concurrency: 4, signal: AbortSignal.abort() })).toEqual([
			{ status: 'late' },
			{ status: 'late' }
		]);
		expect(task).not.toHaveBeenCalled();
	});
});

describe('organizationCatalogs', () => {
	it('reads page after page until it has the first 50 catalogs', async () => {
		const all = Array.from({ length: 50 }, (_, index) => numbered(index + 1));
		const fake = stub({
			'/catalogs?organization=helio&limit=50': jsonResponse(pageFixture(all.slice(0, 20), 'p2')),
			'/catalogs?organization=helio&cursor=p2&limit=50': jsonResponse(
				pageFixture(all.slice(20, 40), 'p3')
			),
			'/catalogs?organization=helio&cursor=p3&limit=50': jsonResponse(pageFixture(all.slice(40)))
		});
		const { event } = orgSearchEvent();
		expect(await organizationCatalogs(api(event), 'helio')).toEqual({
			catalogs: all,
			truncated: false
		});
		expect(fake.calls).toHaveLength(3);
	});

	it('covers the first 50 and says so when the organization has more', async () => {
		const all = Array.from({ length: 60 }, (_, index) => numbered(index + 1));
		const fake = stub({
			'/catalogs?organization=helio&limit=50': jsonResponse(pageFixture(all.slice(0, 30), 'p2')),
			'/catalogs?organization=helio&cursor=p2&limit=50': jsonResponse(
				pageFixture(all.slice(30), null)
			)
		});
		const { event } = orgSearchEvent();
		const listed = await organizationCatalogs(api(event), 'helio');
		expect(listed.catalogs).toEqual(all.slice(0, 50));
		expect(listed.truncated).toBe(true);
		expect(fake.calls).toHaveLength(2);
	});

	it('stops reading once it has 50, when a next page says there are more', async () => {
		const all = Array.from({ length: 50 }, (_, index) => numbered(index + 1));
		const fake = stub({
			'/catalogs?organization=helio&limit=50': jsonResponse(pageFixture(all, 'p2'))
		});
		const { event } = orgSearchEvent();
		expect(await organizationCatalogs(api(event), 'helio')).toEqual({
			catalogs: all,
			truncated: true
		});
		expect(fake.calls).toHaveLength(1);
	});

	it('ends at an empty page, whatever its cursor says', async () => {
		const fake = stub({
			'/catalogs?organization=helio&limit=50': jsonResponse(pageFixture([HELIOPHYSICS], 'p2')),
			'/catalogs?organization=helio&cursor=p2&limit=50': jsonResponse(pageFixture([], 'p2'))
		});
		const { event } = orgSearchEvent();
		expect(await organizationCatalogs(api(event), 'helio')).toEqual({
			catalogs: [HELIOPHYSICS],
			truncated: false
		});
		expect(fake.calls).toHaveLength(2);
	});

	it('fails as the API does for an organization the user cannot see', async () => {
		stub({ '/catalogs?organization=astro&limit=50': problemResponse(404, 'NOT_FOUND') });
		const { event } = orgSearchEvent();
		await expect(organizationCatalogs(api(event), 'astro')).rejects.toMatchObject({
			status: 404
		});
	});
});

describe('searchOrganization', () => {
	it('asks each catalog for its first five results and says which have more', async () => {
		const fake = stub({
			[searchPath('heliophysics')]: jsonResponse(pageFixture([MAG, SWEPAM], 'more')),
			[searchPath('space-weather')]: jsonResponse(pageFixture([KP]))
		});
		const searched = searchFor({ q: 'wind' });
		expect(await search([HELIOPHYSICS, SPACE_WEATHER], searched)).toEqual({
			exact: null,
			answers: [
				{
					name: 'heliophysics',
					displayName: 'Heliophysics',
					search: searched,
					status: 'answered',
					results: [searchResult(MAG), searchResult(SWEPAM)],
					more: true
				},
				{
					name: 'space-weather',
					displayName: 'Space Weather',
					search: searched,
					status: 'answered',
					results: [searchResult(KP)],
					more: false
				}
			],
			late: [],
			skipped: [],
			refused: null
		});
		expect(fake.calls.map(({ url }) => new URL(url).searchParams.get('limit'))).toEqual(['5', '5']);
	});

	it('sends the text, the labels and the chosen states to every catalog', async () => {
		const query = 'q=solar+wind&label=mission%3Dace&state=incomplete';
		const fake = stub({
			[searchPath('heliophysics', query)]: jsonResponse(pageFixture([])),
			[searchPath('space-weather', query)]: jsonResponse(pageFixture([]))
		});
		const searched = searchFor({
			q: 'solar wind',
			labels: [{ key: 'mission', value: 'ace' }],
			states: ['incomplete']
		});
		const { answers } = await search([HELIOPHYSICS, SPACE_WEATHER], searched);
		expect(answers.map(({ status }) => status)).toEqual(['answered', 'answered']);
		expect(fake.calls).toHaveLength(2);
	});

	it(`never asks more than ${CONCURRENCY} catalogs at once`, async () => {
		const catalogs = Array.from({ length: 10 }, (_, index) => numbered(index + 1));
		const waiting: Array<() => void> = [];
		let running = 0;
		let most = 0;
		const held: FetchAnswer = () => {
			running += 1;
			most = Math.max(most, running);
			return new Promise<Response>((resolve) =>
				waiting.push(() => {
					running -= 1;
					resolve(jsonResponse(pageFixture([])));
				})
			);
		};
		const fake = stub(Object.fromEntries(catalogs.map(({ name }) => [searchPath(name), held])));
		let done = false;
		const searching = search(catalogs, searchFor({ q: 'wind' })).finally(() => (done = true));
		while (!done) {
			await vi.waitFor(() => expect(done || waiting.length > 0).toBe(true));
			waiting.shift()?.();
		}
		const { answers, late } = await searching;
		expect(CONCURRENCY).toBe(4);
		expect(most).toBe(4);
		expect(fake.calls).toHaveLength(10);
		expect(answers).toHaveLength(10);
		expect(late).toEqual([]);
	});

	it(`counts the exact match's lookup among the ${CONCURRENCY} requests it runs at once`, async () => {
		const catalogs = Array.from({ length: 10 }, (_, index) => numbered(index + 1));
		const q = 'c01.ns.item';
		const waiting: Array<() => void> = [];
		let running = 0;
		let most = 0;
		const held =
			(answer: () => Response): FetchAnswer =>
			() => {
				running += 1;
				most = Math.max(most, running);
				return new Promise<Response>((resolve) =>
					waiting.push(() => {
						running -= 1;
						resolve(answer());
					})
				);
			};
		const item = collectionFixture({
			id: 'c-item',
			identifier: q,
			catalog: 'c01',
			namespace: 'ns',
			name: 'item'
		});
		const fake = stub({
			...Object.fromEntries(
				catalogs.map(({ name }) => [
					searchPath(name, `q=${q}`),
					held(() => jsonResponse(pageFixture([])))
				])
			),
			'/catalogs/c01/collections/ns.item': held(() => jsonResponse(item))
		});
		let done = false;
		const searching = search(catalogs, searchFor({ q })).finally(() => (done = true));
		while (!done) {
			await vi.waitFor(() => expect(done || waiting.length > 0).toBe(true));
			waiting.shift()?.();
		}
		const { exact, answers } = await searching;
		expect(most).toBe(CONCURRENCY);
		// Asked before any catalog's search.
		expect(new URL(fake.calls[0].url).pathname).toBe('/api/v1/catalogs/c01/collections/ns.item');
		expect(fake.calls).toHaveLength(11);
		expect(exact).toEqual(searchResult(item));
		expect(answers).toHaveLength(10);
	});

	it('gives up at the deadline: what answered shows, what did not is late and aborted', async () => {
		vi.useFakeTimers();
		const catalogs = Array.from({ length: 6 }, (_, index) => numbered(index + 1));
		const fake = stub(
			Object.fromEntries(
				catalogs.map(({ name }, index) => [
					searchPath(name),
					index % 2 === 0 ? jsonResponse(pageFixture([MAG])) : hangingAnswer
				])
			)
		);
		let done = false;
		const searching = search(catalogs, searchFor({ q: 'wind' })).finally(() => (done = true));
		await vi.advanceTimersByTimeAsync(DEADLINE_MS - 1);
		expect(done).toBe(false);
		await vi.advanceTimersByTimeAsync(1);
		const { answers, late } = await searching;
		expect(DEADLINE_MS).toBe(8000);
		expect(answers.map(({ name }) => name)).toEqual(['c01', 'c03', 'c05']);
		expect(late.map(({ name }) => name)).toEqual(['c02', 'c04', 'c06']);
		// Three hung at once; the fourth slot went to each catalog that answered in turn.
		expect(fake.calls).toHaveLength(6);
		const hung = fake.calls.filter(({ url }) => /\/c0[246]\//.test(url));
		expect(hung.map(({ init }) => init?.signal?.aborted)).toEqual([true, true, true]);
	});

	it('counts the catalogs it never got to ask as late too', async () => {
		vi.useFakeTimers();
		const catalogs = Array.from({ length: 6 }, (_, index) => numbered(index + 1));
		const fake = stub(
			Object.fromEntries(catalogs.map(({ name }) => [searchPath(name), hangingAnswer]))
		);
		const searching = search(catalogs, searchFor({ q: 'wind' }));
		await vi.advanceTimersByTimeAsync(DEADLINE_MS);
		const { answers, late } = await searching;
		expect(answers).toEqual([]);
		expect(late).toHaveLength(6);
		expect(fake.calls).toHaveLength(CONCURRENCY);
	});

	it('finishes as soon as every catalog answered, without waiting for the deadline', async () => {
		vi.useFakeTimers();
		stub({ [searchPath('heliophysics')]: jsonResponse(pageFixture([MAG])) });
		const { answers } = await search([HELIOPHYSICS], searchFor({ q: 'wind' }));
		expect(answers).toHaveLength(1);
		expect(vi.getTimerCount()).toBe(0);
	});

	it("shows a catalog's failure on its own, logs it and still shows the others", async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		stub({
			[searchPath('heliophysics')]: problemResponse(500, 'INTERNAL', { request_id: 'req-7' }),
			[searchPath('space-weather')]: jsonResponse(pageFixture([KP]))
		});
		const searched = searchFor({ q: 'wind' });
		const { answers, refused } = await search([HELIOPHYSICS, SPACE_WEATHER], searched);
		expect(answers).toEqual([
			{ name: 'heliophysics', displayName: 'Heliophysics', search: searched, status: 'failed' },
			expect.objectContaining({ name: 'space-weather', results: [searchResult(KP)] })
		]);
		expect(refused).toBeNull();
		expect(log).toHaveBeenCalledTimes(1);
		expect(log.mock.calls[0][1]).toMatchObject({ status: 500, requestId: 'req-7' });
		expect(JSON.stringify(answers)).not.toContain('the API explains');
	});

	it('ends the session when a catalog no longer accepts the token', async () => {
		stub({
			[searchPath('heliophysics')]: problemResponse(401, 'TOKEN_INVALID'),
			[searchPath('space-weather')]: jsonResponse(pageFixture([KP]))
		});
		const { event, sessionId } = orgSearchEvent();
		const outcome = await searchOrganization(event, api(event), {
			search: searchFor({ q: 'wind' }),
			catalogs: [HELIOPHYSICS, SPACE_WEATHER],
			access: READER
		}).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toMatch(/^\/login\?status=expired&/);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it('ends the session when the exact match is looked up with a token no longer accepted', async () => {
		const q = 'heliophysics.solar-wind.ace.mag-l2-2024';
		stub({
			[searchPath('heliophysics', `q=${q}`)]: jsonResponse(pageFixture([MAG])),
			[searchPath('space-weather', `q=${q}`)]: jsonResponse(pageFixture([])),
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024': problemResponse(
				401,
				'TOKEN_INVALID'
			)
		});
		const { event, sessionId } = orgSearchEvent();
		const outcome = await searchOrganization(event, api(event), {
			search: searchFor({ q }),
			catalogs: [HELIOPHYSICS, SPACE_WEATHER],
			access: READER
		}).catch((thrown: unknown) => thrown);
		expect(isRedirect(outcome) && outcome.location).toMatch(/^\/login\?status=expired&/);
		expect(sessionStore().user(sessionId)).toBeUndefined();
	});

	it('returns a refusal of the API for the form, as the catalog search shows it', async () => {
		stub({
			[searchPath('heliophysics')]: problemResponse(422, 'REQUEST_INVALID', {
				problems: [{ path: '/query/q' }]
			}),
			[searchPath('space-weather')]: jsonResponse(pageFixture([KP]))
		});
		const { refused } = await search([HELIOPHYSICS, SPACE_WEATHER], searchFor({ q: 'wind' }));
		expect(refused).toEqual({
			q: "The Huron service didn't accept this text.",
			label: null,
			form: null
		});
	});

	it('sends drafts only to the catalogs whose drafts the user may see', async () => {
		const fake = stub({
			[searchPath('heliophysics', 'q=wind&state=incomplete&state=draft')]: jsonResponse(
				pageFixture([])
			),
			[searchPath('space-weather', 'q=wind&state=incomplete')]: jsonResponse(pageFixture([]))
		});
		const searched = searchFor({ q: 'wind', states: ['incomplete', 'draft'] });
		const { answers, skipped } = await search([HELIOPHYSICS, SPACE_WEATHER], searched, CONTRIBUTOR);
		expect(answers.map(({ name, search: own }) => [name, own.states])).toEqual([
			['heliophysics', ['incomplete', 'draft']],
			['space-weather', ['incomplete']]
		]);
		expect(skipped).toEqual([]);
		expect(fake.calls).toHaveLength(2);
	});

	it('skips a catalog where a search for drafts alone has nothing left to search', async () => {
		const fake = stub({
			[searchPath('heliophysics', 'state=draft')]: jsonResponse(pageFixture([]))
		});
		const { answers, skipped } = await search(
			[HELIOPHYSICS, SPACE_WEATHER],
			searchFor({ states: ['draft'] }),
			CONTRIBUTOR
		);
		expect(answers.map(({ name }) => name)).toEqual(['heliophysics']);
		expect(skipped).toEqual([{ name: 'space-weather', displayName: 'Space Weather' }]);
		expect(fake.calls.map(({ url }) => url)).not.toContainEqual(
			expect.stringContaining('space-weather')
		);
	});

	it('shows the collection a full identifier names first, and not again in its catalog', async () => {
		const q = 'heliophysics.solar-wind.ace.mag-l2-2024';
		const fake = stub({
			[searchPath('heliophysics', `q=${q}`)]: jsonResponse(pageFixture([MAG, SWEPAM])),
			[searchPath('space-weather', `q=${q}`)]: jsonResponse(pageFixture([])),
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024': jsonResponse(MAG)
		});
		const { exact, answers } = await search([HELIOPHYSICS, SPACE_WEATHER], searchFor({ q }));
		expect(exact).toEqual(searchResult(MAG));
		expect(answers[0]).toMatchObject({ status: 'answered', results: [searchResult(SWEPAM)] });
		expect(fake.calls).toHaveLength(3);
	});

	it('looks up the exact match with the search its catalog gets, filters and all', async () => {
		const draft: Collection = { ...MAG, state: 'draft' };
		const q = 'heliophysics.solar-wind.ace.mag-l2-2024';
		stub({
			[searchPath('heliophysics', `q=${q}`)]: jsonResponse(pageFixture([])),
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024': jsonResponse(draft)
		});
		// A draft is no result of a search over the default states.
		const { exact } = await search([HELIOPHYSICS], searchFor({ q }), CONTRIBUTOR);
		expect(exact).toBeNull();
	});

	it.each([
		['a catalog outside the organization', 'geoscience.ocean.sst-2024'],
		['no catalog, inside one of them', 'solar-wind.ace.mag-l2-2024']
	])('never looks up an identifier of %s', async (_, q) => {
		const fake = stub({
			[searchPath('heliophysics', `q=${q}`)]: jsonResponse(pageFixture([])),
			[searchPath('space-weather', `q=${q}`)]: jsonResponse(pageFixture([]))
		});
		const { exact } = await search([HELIOPHYSICS, SPACE_WEATHER], searchFor({ q }));
		expect(exact).toBeNull();
		expect(fake.calls.map(({ url }) => new URL(url).pathname)).toEqual([
			'/api/v1/catalogs/heliophysics/search',
			'/api/v1/catalogs/space-weather/search'
		]);
	});

	it('gives the exact match up at the deadline too, without a word', async () => {
		vi.useFakeTimers();
		const log = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const q = 'heliophysics.solar-wind.ace.mag-l2-2024';
		stub({
			[searchPath('heliophysics', `q=${q}`)]: jsonResponse(pageFixture([MAG])),
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024': hangingAnswer
		});
		let done = false;
		const searching = search([HELIOPHYSICS], searchFor({ q })).finally(() => (done = true));
		await vi.advanceTimersByTimeAsync(DEADLINE_MS - 1);
		expect(done).toBe(false);
		await vi.advanceTimersByTimeAsync(1);
		const { exact, answers, late } = await searching;
		expect(exact).toBeNull();
		expect(answers[0]).toMatchObject({ results: [searchResult(MAG)] });
		expect(late).toEqual([]);
		expect(log).not.toHaveBeenCalled();
	});

	it('searches nothing among no catalogs', async () => {
		const fake = stub({});
		expect(await search([], searchFor({ q: 'wind' }))).toEqual({
			exact: null,
			answers: [],
			late: [],
			skipped: [],
			refused: null
		});
		expect(fake.calls).toHaveLength(0);
	});
});
