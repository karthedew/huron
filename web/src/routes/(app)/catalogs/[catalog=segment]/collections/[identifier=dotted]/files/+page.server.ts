import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import { pageCollection } from '$lib/server/collection';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * The files a collection records, sorted by path, a page at a time. A draft has no directory and
 * so no files: there is nothing to read.
 */
export const load = (async (event) => {
	const collection = await pageCollection(event);
	if (collection.state === 'draft') return { files: [], nextCursor: null };
	const list = await guarded(
		event,
		api(event).files(collection.id, { cursor: cursorParam(event.url), limit: LIST_PAGE_SIZE })
	);
	return { files: list.items, nextCursor: list.next_cursor ?? null };
}) satisfies PageServerLoad;
