import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import { schemaNames } from '$lib/server/activity';
import { pageCollection } from '$lib/server/collection';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * The audit entries about a collection, newest first, a page at a time. Their detail keys are
 * fixed by the core, so the entries leave as they are.
 */
export const load = (async (event) => {
	const client = api(event);
	const collection = await pageCollection(event);
	const log = await guarded(
		event,
		client.collectionLog(collection.id, { cursor: cursorParam(event.url), limit: LIST_PAGE_SIZE })
	);
	return {
		entries: log.items,
		nextCursor: log.next_cursor ?? null,
		schemas: await schemaNames(event, client, log.items)
	};
}) satisfies PageServerLoad;
