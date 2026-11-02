import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import { pageCollection } from '$lib/server/collection';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * A collection's commits, newest first, a page at a time. Only a collection with a directory
 * takes commits: a draft has none to read.
 */
export const load = (async (event) => {
	const collection = await pageCollection(event);
	if (collection.state === 'draft') return { commits: [], nextCursor: null };
	const list = await guarded(
		event,
		api(event).commits(collection.id, { cursor: cursorParam(event.url), limit: LIST_PAGE_SIZE })
	);
	return { commits: list.items, nextCursor: list.next_cursor ?? null };
}) satisfies PageServerLoad;
