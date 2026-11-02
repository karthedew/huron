import { explorerLevel, pathPrefixes, type ExplorerLevel, type TrailLevel } from '../explorer';
import { LIST_PAGE_SIZE } from '../paging';
import { fanOut } from './fan-out';
import { degrade, type GuardEvent } from './guard';
import type { HuronApi } from './huron-api';

/**
 * How many levels of a trail load at once; each asks for two lists. A path may have over a
 * hundred levels (identifiers hold up to 255 bytes), and every reader of a page below it would
 * otherwise send all their requests to the API at the same instant.
 */
export const TRAIL_CONCURRENCY = 4;

/**
 * How many collections a level of a trail above the page's own namespace lists, before its
 * "More…" link. The API lists collections whole, each with its metadata of up to a mebibyte,
 * and the explorer shows only their names: every level that read 50 would add their weight to
 * each view of every page below it. The page's own namespace still lists 50.
 */
export const ANCESTOR_COLLECTIONS = 10;

/**
 * One level of the explorer: the first page of a parent's namespaces and, below the catalog
 * root (which holds no collections), of its collections, at most `collections` of them. A page
 * that lists the same parent's first pages shares these reads through the request's memoized
 * client.
 */
export async function loadLevel(
	client: HuronApi,
	catalog: string,
	parent: string,
	collections = LIST_PAGE_SIZE
): Promise<ExplorerLevel> {
	const [namespaces, listed] = await Promise.all([
		client.namespaces(catalog, parent, { limit: LIST_PAGE_SIZE }),
		parent === '' ? null : client.namespaceCollections(catalog, parent, { limit: collections })
	]);
	return explorerLevel(parent, namespaces, listed);
}

/**
 * The levels on the way to a namespace below the root, the namespace's own included
 * (`deep.a` gives the levels of `deep` and `deep.a`), `TRAIL_CONCURRENCY` at a time; those
 * above the namespace list `ANCESTOR_COLLECTIONS` collections. A level whose read fails is a
 * failed level, which the explorer offers to load again, so one namespace that cannot be read
 * fails no page below it; the failure is logged, and an expired Huron token still ends the
 * session.
 */
export async function loadTrail(
	event: GuardEvent,
	client: HuronApi,
	catalog: string,
	path: string
): Promise<TrailLevel[]> {
	const prefixes = pathPrefixes(path);
	const own = prefixes.length - 1;
	// No deadline of its own: each read has the API's timeout.
	const settlements = await fanOut(
		prefixes.map((prefix, index) => ({
			prefix,
			collections: index === own ? LIST_PAGE_SIZE : ANCESTOR_COLLECTIONS
		})),
		({ prefix, collections }) => loadLevel(client, catalog, prefix, collections),
		{ concurrency: TRAIL_CONCURRENCY, signal: new AbortController().signal }
	);
	return settlements.map((settlement, index): TrailLevel => {
		if (settlement.status === 'answered') return settlement.value;
		if (settlement.status === 'failed') degrade(event, settlement.failure);
		return { parent: prefixes[index], failed: true };
	});
}
