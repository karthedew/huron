import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import { schemaNames } from '$lib/server/activity';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * The catalog's audit log, newest first, a page at a time. Readers get pages without the
 * entries about drafts, so a page can be short, or empty, and still have a next one.
 */
export const load = (async (event) => {
	const client = api(event);
	const log = await guarded(
		event,
		client.catalogLog(event.params.catalog, {
			cursor: cursorParam(event.url),
			limit: LIST_PAGE_SIZE
		})
	);
	return {
		entries: log.items,
		nextCursor: log.next_cursor ?? null,
		schemas: await schemaNames(event, client, log.items)
	};
}) satisfies PageServerLoad;
