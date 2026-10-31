import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * The catalog's top-level namespaces, a page at a time. The first page is the read the catalog
 * layout makes for the explorer's root, shared through the request's client.
 */
export const load = (async (event) => {
	const list = await guarded(
		event,
		api(event).namespaces(event.params.catalog, '', {
			cursor: cursorParam(event.url),
			limit: LIST_PAGE_SIZE
		})
	);
	return { namespaces: list.items, nextCursor: list.next_cursor ?? null };
}) satisfies PageServerLoad;
