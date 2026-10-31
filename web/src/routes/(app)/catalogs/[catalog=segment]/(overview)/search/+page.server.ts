import {
	asksForDrafts,
	exactIdentifier,
	hasErrors,
	labelsContradict,
	readSearch,
	searchRequest,
	searchResult,
	type Search,
	type SearchErrors,
	type SearchResult
} from '$lib/search';
import { api, fail, settled, type GuardEvent } from '$lib/server/guard';
import type { HuronApi } from '$lib/server/huron-api';
import { draftAccess, exactMatch, maySeeDrafts, refusedSearch } from '$lib/server/search';
import type { PageServerLoad } from './$types';

interface SearchPage {
	search: Search;
	errors: SearchErrors;
	pendingLabel: string;
	exact: SearchResult | null;
	/** `null` when the search was not sent. */
	results: SearchResult[] | null;
	nextCursor: string | null;
}

/**
 * A search of the catalog, a page of results at a time, from its address (see `readSearch`).
 * A search with errors is never sent: the form shows them at their fields; nor is one whose label
 * filters give a key two values, which no collection passes. Drafts count only for users who may
 * see them, which is asked only when the address asks for drafts. On the first page, the
 * collection the text names exactly comes first, and on no page again among the results.
 * Results go out as plain rows, so their metadata stays on the server; a refusal of the API
 * (422) shows at the form, any other failure is the page's.
 */
export const load = (async (event): Promise<SearchPage> => {
	const client = api(event);
	const { catalog } = event.params;
	const params = event.url.searchParams;
	const drafts = asksForDrafts(params) && (await catalogDrafts(event, client, catalog));
	const { search, errors, pendingLabel } = readSearch(params, { drafts });
	const unsent: SearchPage = {
		search,
		errors,
		pendingLabel,
		exact: null,
		results: null,
		nextCursor: null
	};
	if (hasErrors(errors)) return unsent;
	if (labelsContradict(search)) return { ...unsent, results: [] };
	const [answer, exact] = await Promise.all([
		settled(client.search(catalog, searchRequest(search))),
		exactMatch(event, client, catalog, search)
	]);
	if (!answer.ok) {
		const refused = refusedSearch(answer.failure);
		if (refused === null) fail(event, answer.failure);
		return { ...unsent, errors: refused };
	}
	const lifted = liftedIdentifier(catalog, search, exact);
	return {
		search,
		errors,
		pendingLabel,
		exact,
		results: answer.value.items.map(searchResult).filter(({ identifier }) => identifier !== lifted),
		nextCursor: answer.value.next_cursor ?? null
	};
}) satisfies PageServerLoad;

/**
 * The result the exact match takes out of the list: on the first page the collection it found;
 * on a later page the one the text names, which the first page showed at its top. Its being among
 * the results shows that it passes the search's filters, so no page looks it up again.
 */
function liftedIdentifier(
	catalog: string,
	search: Search,
	exact: SearchResult | null
): string | null {
	if (search.cursor === null) return exact?.identifier ?? null;
	const named = exactIdentifier(search.q, catalog);
	return named === null ? null : `${catalog}.${named}`;
}

/**
 * Whether the user may search this catalog's drafts. The catalog is the read the catalog layout
 * makes; its failure is the layout's to show.
 */
async function catalogDrafts(event: GuardEvent, client: HuronApi, name: string): Promise<boolean> {
	const [access, catalog] = await Promise.all([
		draftAccess(event, client),
		settled(client.catalog(name))
	]);
	return catalog.ok && maySeeDrafts(access, catalog.value);
}
