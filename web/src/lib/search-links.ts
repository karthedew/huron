/** Addresses for the single collection search page and its explicit scope. */
import { resolve } from '$app/paths';
import type { Named } from './names';
import { searchParams, type Search } from './search';

/** Catalog choices shown by the search form for its selected organization. */
export interface SearchCatalogScope {
	organization: string;
	catalog: string | null;
	catalogs: Named[];
}

/** The central search page, with an explicit organization or catalog when selected. */
export function searchHref(
	search: Search,
	{ organization, catalog }: { organization?: string | null; catalog?: string | null } = {}
): string {
	const params = new URLSearchParams();
	if (organization) params.set('organization', organization);
	if (catalog) params.set('catalog', catalog);
	for (const [key, value] of searchParams(search)) params.append(key, value);
	const query = params.toString();
	return `${resolve('/(app)/search')}${query === '' ? '' : `?${query}`}`;
}

/** Search one catalog from any collection or label link. */
export function catalogSearchHref(catalog: string, search: Search): string {
	return searchHref(search, { catalog });
}

/** Search all visible catalogs in an organization. */
export function organizationSearchHref(organization: string, search: Search): string {
	return searchHref(search, { organization });
}

/** Preserve supported input on a legacy search URL, including text needing correction. */
export function legacySearchHref(
	params: URLSearchParams,
	scope: { organization?: string; catalog?: string }
): string {
	const kept = new URLSearchParams();
	if (scope.organization) kept.set('organization', scope.organization);
	if (scope.catalog) kept.set('catalog', scope.catalog);
	for (const [key, value] of params) {
		if (['q', 'label', 'label_json', 'state', 'cursor', 'notice'].includes(key)) {
			kept.append(key, value);
		}
	}
	return `${resolve('/(app)/search')}?${kept.toString()}`;
}
