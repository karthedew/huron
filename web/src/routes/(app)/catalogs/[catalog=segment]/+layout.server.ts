import { loadLevel } from '$lib/server/explorer';
import { api, guarded } from '$lib/server/guard';
import type { LayoutServerLoad } from './$types';

/** The explorer's top level: enough of the organization's catalogs for any real organization. */
const CATALOG_LIMIT = 100;

/**
 * Every page of a catalog: the catalog, its organization's catalogs and the root of its tree for
 * the explorer. The catalog and the root load in parallel; the organization's catalogs follow
 * the catalog, which names the organization. The organization becomes the shell's current one.
 * A catalog the user cannot see is concealed by the API as not found.
 */
export const load = (async (event) => {
	const client = api(event);
	const name = event.params.catalog;
	const catalogRead = client.catalog(name);
	const [catalog, siblings, root] = await Promise.all([
		guarded(event, catalogRead),
		guarded(
			event,
			catalogRead.then(({ organization }) =>
				client.catalogs({ organization, limit: CATALOG_LIMIT })
			)
		),
		guarded(event, loadLevel(client, name, ''))
	]);
	return {
		organization: catalog.organization,
		catalog,
		catalogs: siblings.items.map(({ name, display_name }) => ({ name, display_name })),
		moreCatalogs: (siblings.next_cursor ?? null) !== null,
		root
	};
}) satisfies LayoutServerLoad;
