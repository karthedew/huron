import { collectionSummary } from '$lib/collections';
import { getConfig } from '$lib/server/config';
import { loadTrail } from '$lib/server/explorer';
import { api, guarded } from '$lib/server/guard';
import type { LayoutServerLoad } from './$types';

/**
 * Every page of a collection: the collection, by its identifier within the catalog, and the
 * explorer's levels on the way to it. The levels follow the collection, so a made-up identifier
 * costs no read per segment. The collection leaves as its summary; its metadata stays here.
 */
export const load = (async (event) => {
	const client = api(event);
	const { catalog, identifier } = event.params;
	const found = client.collectionByIdentifier(catalog, identifier);
	const [collection, trail] = await Promise.all([
		guarded(event, found),
		guarded(
			event,
			found.then(({ namespace }) => loadTrail(event, client, catalog, namespace))
		)
	]);
	return { collection: collectionSummary(collection, getConfig().mountPrefix), trail };
}) satisfies LayoutServerLoad;
