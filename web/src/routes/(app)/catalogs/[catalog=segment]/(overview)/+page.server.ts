import { readBrowseSort } from '$lib/browse-sort';
import { BROWSE_PAGE_SIZE, cursorParam } from '$lib/paging';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * The catalog's top-level namespaces, globally sorted before the API takes one page.
 */
export const load = (async (event) => {
	const namespaceSort = readBrowseSort(event.url);
	const list = await guarded(
		event,
		api(event).namespaces(event.params.catalog, '', {
			cursor: cursorParam(event.url),
			limit: BROWSE_PAGE_SIZE,
			...namespaceSort
		})
	);
	return { namespaces: list.items, nextCursor: list.next_cursor ?? null, namespaceSort };
}) satisfies PageServerLoad;
