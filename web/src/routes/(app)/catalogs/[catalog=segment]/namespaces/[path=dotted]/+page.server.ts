import { readBrowseSort } from '$lib/browse-sort';
import { collectionRow } from '$lib/collections';
import { BROWSE_PAGE_SIZE, cursorParam } from '$lib/paging';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/** The namespace's two lists, each globally sorted and paged independently by the API. */
export const load = (async (event) => {
	const client = api(event);
	const { catalog, path } = event.params;
	const namespaceSort = readBrowseSort(event.url, 'namespaces');
	const collectionSort = readBrowseSort(event.url, 'collections');
	const [namespaces, collections] = await Promise.all([
		guarded(
			event,
			client.namespaces(catalog, path, {
				cursor: cursorParam(event.url, 'namespaces_cursor'),
				limit: BROWSE_PAGE_SIZE,
				...namespaceSort
			})
		),
		guarded(
			event,
			client.namespaceCollections(catalog, path, {
				cursor: cursorParam(event.url, 'collections_cursor'),
				limit: BROWSE_PAGE_SIZE,
				...collectionSort
			})
		)
	]);
	return {
		namespaces: namespaces.items,
		namespacesNext: namespaces.next_cursor ?? null,
		namespaceSort,
		collections: collections.items.map(collectionRow),
		collectionsNext: collections.next_cursor ?? null,
		collectionSort
	};
}) satisfies PageServerLoad;
