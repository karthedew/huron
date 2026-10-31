/** Items per page of a list (organizations, catalogs, namespaces, files, …). */
export const LIST_PAGE_SIZE = 50;

/** Results per page of a search. */
export const SEARCH_PAGE_SIZE = 25;

/**
 * The keyset cursor of a list in a URL: `cursor`, or `<list>_cursor` on a page with two lists.
 * An empty value means the first page.
 */
export function cursorParam(url: URL, name = 'cursor'): string | null {
	return url.searchParams.get(name) || null;
}

/** Whether a query parameter carries a keyset cursor (`cursor` or `<list>_cursor`). */
export function isCursorParameter(key: string): boolean {
	return key === 'cursor' || key.endsWith('_cursor');
}
