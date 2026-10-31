/**
 * The addresses of the pages that search, for a search (see `search.ts`), and what the shell's
 * search box and its Search item search.
 */
import { resolve } from '$app/paths';
import { displayName, type Named } from './names';
import { emptySearch, searchQuery, type Search } from './search';

/** The address of a catalog's search page for a search. */
export function catalogSearchHref(catalog: string, search: Search): string {
	const path = resolve('/(app)/catalogs/[catalog=segment]/(overview)/search', { catalog });
	return `${path}${searchQuery(search)}`;
}

/** The address of an organization's search page, over its catalogs, for a search. */
export function organizationSearchHref(organization: string, search: Search): string {
	const path = resolve('/(app)/orgs/[org=segment]/search', { org: organization });
	return `${path}${searchQuery(search)}`;
}

/** The address of the page that asks which organization to search, for a search. */
export function chooserHref(search: Search): string {
	return `${resolve('/search')}${searchQuery(search)}`;
}

/** What the shell's search box and its Search item search. */
export interface SearchScope {
	/** The search page, without a query. */
	href: string;
	/** The name of the catalog or organization searched; `null` where the page asks which. */
	name: string | null;
}

/**
 * The shell's search scope: the catalog of a catalog's page; else the shell's current
 * organization, the page's or the remembered one; else the page that asks which organization
 * to search.
 */
export function searchScope(
	catalog: Named | null | undefined,
	organization: Named | null
): SearchScope {
	if (catalog) {
		return { href: catalogSearchHref(catalog.name, emptySearch()), name: displayName(catalog) };
	}
	if (organization) {
		return {
			href: organizationSearchHref(organization.name, emptySearch()),
			name: displayName(organization)
		};
	}
	return { href: chooserHref(emptySearch()), name: null };
}
