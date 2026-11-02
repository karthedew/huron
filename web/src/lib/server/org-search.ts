/**
 * The organization search. The API searches one catalog at a time, so the web asks each catalog
 * of an organization for its first results, a few catalogs at once, until a deadline: a catalog
 * that has not answered by then is given up, its request aborted, and the page shows what came
 * in time.
 *
 * `fanOut` runs such tasks, `organizationCatalogs` lists the catalogs to search and
 * `searchOrganization` searches them, every answer turned into plain rows, as loads return them.
 */
import type { Catalog } from '$api/types';
import { displayName } from '$lib/names';
import {
	CATALOG_RESULTS,
	ORGANIZATION_CATALOGS,
	identifiedCatalog,
	searchRequest,
	searchResult,
	withoutDrafts,
	type Search,
	type SearchErrors,
	type SearchResult
} from '$lib/search';
import { fanOut, type Settlement } from './fan-out';
import { degrade, type GuardEvent } from './guard';
import type { HuronApi } from './huron-api';
import { exactMatch, maySeeDrafts, refusedSearch, type DraftAccess } from './search';

/** How many requests an organization's search runs at once, the exact match's lookup among them. */
export const CONCURRENCY = 4;

/** How long an organization's search waits for its catalogs in all, in milliseconds. */
export const DEADLINE_MS = 8_000;

export { fanOut, type Settlement };

/** Calls `run` after `ms` milliseconds, unless the function it returns is called before. */
export type Timer = (run: () => void, ms: number) => () => void;

/** The timer of the global `setTimeout`, which tests may fake. */
export const systemTimer: Timer = (run, ms) => {
	const handle = setTimeout(run, ms);
	return () => clearTimeout(handle);
};

/** The catalogs an organization's search covers. */
export interface SearchedCatalogs {
	/** The organization's first catalogs that the user can see, by name, as many as it covers. */
	catalogs: Catalog[];
	/** Whether the organization has more catalogs, which the search leaves out. */
	truncated: boolean;
}

/**
 * The first `ORGANIZATION_CATALOGS` catalogs of an organization that the user can see, read page
 * after page, and whether it has more. The API conceals an organization the user cannot see as
 * not found.
 */
export async function organizationCatalogs(
	client: HuronApi,
	organization: string
): Promise<SearchedCatalogs> {
	const catalogs: Catalog[] = [];
	let cursor: string | null = null;
	do {
		const page = await client.catalogs({ organization, cursor, limit: ORGANIZATION_CATALOGS });
		catalogs.push(...page.items);
		// An empty page ends the list, whatever its cursor says: a list never goes on forever.
		cursor = page.items.length === 0 ? null : (page.next_cursor ?? null);
	} while (cursor !== null && catalogs.length < ORGANIZATION_CATALOGS);
	return {
		catalogs: catalogs.slice(0, ORGANIZATION_CATALOGS),
		truncated: cursor !== null || catalogs.length > ORGANIZATION_CATALOGS
	};
}

/** A catalog by its names. */
export interface CatalogName {
	name: string;
	displayName: string;
}

/** A catalog an organization's search asks, and what it asks it. */
export interface SearchedCatalog extends CatalogName {
	/** The search as this catalog gets it: with drafts only where the user may see them. */
	search: Search;
}

/** What a catalog answered in time, or that its search failed. */
export type CatalogAnswer = SearchedCatalog &
	(
		| {
				status: 'answered';
				/** Its first results, without the exact match, which shows on its own. */
				results: SearchResult[];
				/** Whether it has more results than its first ones. */
				more: boolean;
		  }
		| { status: 'failed' }
	);

/** What an organization's search found, as plain rows. */
export interface OrganizationResults {
	/** The collection its text names by a full identifier, when the search finds it. */
	exact: SearchResult | null;
	/** Each catalog that answered in time, or failed, in the organization's order. */
	answers: CatalogAnswer[];
	/** The catalogs that had not answered at the deadline, in the organization's order. */
	late: SearchedCatalog[];
	/** The catalogs left out: the search asks for drafts only, which they never show the user. */
	skipped: CatalogName[];
	/** Set when the API refused the search as invalid: what the form says at its fields. */
	refused: SearchErrors | null;
}

/** Changes for tests. */
export interface SearchOptions {
	timer?: Timer;
}

/**
 * Search the catalogs of an organization for their first `CATALOG_RESULTS` results each,
 * within `DEADLINE_MS` in all, `CONCURRENCY` requests at once. Each catalog includes drafts
 * only where the user may see them, so draft is never sent elsewhere, and a catalog left with no
 * state to search is skipped. The exact match is looked up only where a full identifier names
 * one of these catalogs, never elsewhere: one more request of the same fan-out, asked first.
 *
 * At the deadline the requests still running are aborted, and their catalogs are late. A
 * catalog's failure is its own: it is logged, and the other catalogs still show; an expired
 * Huron token ends the session, and a refusal (422) is returned for the form, as the catalog
 * search shows it. Bugs are thrown.
 */
export async function searchOrganization(
	event: GuardEvent,
	client: HuronApi,
	{
		search,
		catalogs,
		access
	}: { search: Search; catalogs: readonly Catalog[]; access: DraftAccess },
	{ timer = systemTimer }: SearchOptions = {}
): Promise<OrganizationResults> {
	const targets: SearchedCatalog[] = [];
	const skipped: CatalogName[] = [];
	for (const catalog of catalogs) {
		const named = { name: catalog.name, displayName: displayName(catalog) };
		const own = maySeeDrafts(access, catalog) ? search : withoutDrafts(search);
		if (own === null) skipped.push(named);
		else targets.push({ ...named, search: own });
	}
	const identified = identifiedCatalog(
		search.q,
		targets.map(({ name }) => name)
	);
	const owner = targets.find(({ name }) => name === identified);
	const questions = targets.map((target): Question => ({ kind: 'results', target }));
	if (owner !== undefined) questions.unshift({ kind: 'exact', target: owner });
	const deadline = new AbortController();
	const stop = timer(() => deadline.abort(), DEADLINE_MS);
	try {
		const settlements = await fanOut(
			questions,
			(question, signal) => ask(event, client, question, signal),
			{ concurrency: CONCURRENCY, signal: deadline.signal }
		);
		return { ...answered(event, questions, settlements), skipped };
	} finally {
		stop();
		// Nothing keeps running once the search is over, also when a failure ends it early.
		deadline.abort();
	}
}

/** One request of an organization's search: a catalog's first results, or its exact match. */
interface Question {
	kind: 'results' | 'exact';
	target: SearchedCatalog;
}

/** What a catalog answers a question: the exact match is one result or none, with no more. */
interface Reply {
	results: SearchResult[];
	more: boolean;
}

/** Ask a catalog a question, the rows of its reply plain. */
async function ask(
	event: GuardEvent,
	client: HuronApi,
	{ kind, target }: Question,
	signal: AbortSignal
): Promise<Reply> {
	if (kind === 'exact') {
		const exact = await exactMatch(event, client, target.name, target.search, { signal });
		return { results: exact === null ? [] : [exact], more: false };
	}
	const page = await client.search(
		target.name,
		{ ...searchRequest(target.search), limit: CATALOG_RESULTS },
		{ signal }
	);
	return { results: page.items.map(searchResult), more: (page.next_cursor ?? null) !== null };
}

/** What each question's settlement means for the page. */
function answered(
	event: GuardEvent,
	questions: readonly Question[],
	settlements: ReadonlyArray<Settlement<Reply>>
): Omit<OrganizationResults, 'skipped'> {
	let exact: SearchResult | null = null;
	const replies: Array<{ target: SearchedCatalog; settlement: Settlement<Reply> }> = [];
	for (const [index, settlement] of settlements.entries()) {
		const { kind, target } = questions[index];
		if (kind === 'results') {
			replies.push({ target, settlement });
		} else if (settlement.status === 'answered') {
			exact = settlement.value.results[0] ?? null;
		} else if (settlement.status === 'failed') {
			// The lookup fails only where the session ends, or by a bug; a late one shows nothing.
			degrade(event, settlement.failure);
		}
	}
	const answers: CatalogAnswer[] = [];
	const late: SearchedCatalog[] = [];
	let refused: SearchErrors | null = null;
	for (const { target, settlement } of replies) {
		if (settlement.status === 'late') {
			late.push(target);
		} else if (settlement.status === 'answered') {
			const { results, more } = settlement.value;
			answers.push({
				...target,
				status: 'answered',
				results: results.filter(({ identifier }) => identifier !== exact?.identifier),
				more
			});
		} else {
			const refusal = refusedSearch(settlement.failure);
			if (refusal === null) degrade(event, settlement.failure);
			refused ??= refusal;
			answers.push({ ...target, status: 'failed' });
		}
	}
	return { exact, answers, late, refused };
}
