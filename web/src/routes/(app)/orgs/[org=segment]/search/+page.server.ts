import {
	atPage,
	hasErrors,
	isEmptySearch,
	labelsContradict,
	readSearch,
	type Search,
	type SearchErrors
} from '$lib/search';
import { api, guarded } from '$lib/server/guard';
import {
	organizationCatalogs,
	searchOrganization,
	type OrganizationResults
} from '$lib/server/org-search';
import { draftAccess, maySeeDrafts } from '$lib/server/search';
import type { PageServerLoad } from './$types';

interface OrganizationSearchPage {
	search: Search;
	errors: SearchErrors;
	pendingLabel: string;
	/** Whether the form offers drafts: the user may create collections in one of the catalogs. */
	drafts: boolean;
	/** How many catalogs the search covers. */
	catalogCount: number;
	/** Whether the organization has more catalogs than the search covers. */
	truncated: boolean;
	/** `null` when the search was not sent. */
	results: Omit<OrganizationResults, 'refused'> | null;
}

/**
 * A search of the organization: of each of its first catalogs (see `searchOrganization`), from
 * its address, read and checked once for all of them (see `readSearch`). The form offers drafts
 * when the user may create collections in one of the catalogs. Nothing is sent for a search with
 * errors, which the form shows at their fields, nor for the empty search: the page has no
 * results of its own to list, and the organization's Catalogs page lists its catalogs. Label
 * filters that give a key two values find nothing without asking. The search has no pages:
 * each catalog's own search shows the rest of its results.
 */
export const load = (async (event): Promise<OrganizationSearchPage> => {
	const client = api(event);
	const [{ catalogs, truncated }, access] = await Promise.all([
		guarded(event, organizationCatalogs(client, event.params.org)),
		draftAccess(event, client)
	]);
	const drafts = catalogs.some((catalog) => maySeeDrafts(access, catalog));
	const read = readSearch(event.url.searchParams, { drafts });
	const search = atPage(read.search, null);
	const unsent: OrganizationSearchPage = {
		search,
		errors: read.errors,
		pendingLabel: read.pendingLabel,
		drafts,
		catalogCount: catalogs.length,
		truncated,
		results: null
	};
	if (hasErrors(read.errors) || isEmptySearch(search) || catalogs.length === 0) return unsent;
	if (labelsContradict(search)) {
		return { ...unsent, results: { exact: null, answers: [], late: [], skipped: [] } };
	}
	const { refused, ...results } = await searchOrganization(event, client, {
		search,
		catalogs,
		access
	});
	return refused === null ? { ...unsent, results } : { ...unsent, errors: refused };
}) satisfies PageServerLoad;
