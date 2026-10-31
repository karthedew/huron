import { collectionRow } from '$lib/collections';
import { LIST_PAGE_SIZE, cursorParam } from '$lib/paging';
import { getConfig } from '$lib/server/config';
import { loadTrail } from '$lib/server/explorer';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * A namespace: its child namespaces and its collections, each list paged by its own cursor, and
 * the explorer's levels on the way to it. The namespace and its lists load in parallel; the
 * trail's levels follow the namespace, in parallel, so a made-up path costs no read per segment.
 * The first pages of the two lists are the reads of the namespace's own level in the trail,
 * shared through the request's client. Collections go out as rows, so their metadata stays on the
 * server (see `CollectionRow`).
 */
export const load = (async (event) => {
	const client = api(event);
	const { catalog, path } = event.params;
	const found = client.namespace(catalog, path);
	const [namespace, namespaces, collections, trail] = await Promise.all([
		guarded(event, found),
		guarded(
			event,
			client.namespaces(catalog, path, {
				cursor: cursorParam(event.url, 'namespaces_cursor'),
				limit: LIST_PAGE_SIZE
			})
		),
		guarded(
			event,
			client.namespaceCollections(catalog, path, {
				cursor: cursorParam(event.url, 'collections_cursor'),
				limit: LIST_PAGE_SIZE
			})
		),
		guarded(
			event,
			found.then(() => loadTrail(event, client, catalog, path))
		)
	]);
	return {
		namespace,
		/** Where the namespace's directory is on the share (the CLI's `Mount.path`). */
		sharePath: `${getConfig().mountPrefix}/${namespace.disk_path}`,
		namespaces: namespaces.items,
		namespacesNext: namespaces.next_cursor ?? null,
		collections: collections.items.map(collectionRow),
		collectionsNext: collections.next_cursor ?? null,
		trail
	};
}) satisfies PageServerLoad;
