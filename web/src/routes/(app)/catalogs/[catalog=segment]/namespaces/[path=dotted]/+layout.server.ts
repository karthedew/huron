import { getConfig } from '$lib/server/config';
import { loadTrail } from '$lib/server/explorer';
import { api, guarded } from '$lib/server/guard';
import { sharePath } from '$lib/share';
import type { LayoutServerLoad } from './$types';

/** The namespace and its Explorer trail shared by Overview and CLI. */
export const load = (async (event) => {
	const client = api(event);
	const { catalog, path } = event.params;
	const namespace = await guarded(event, client.namespace(catalog, path));
	const trail = await guarded(event, loadTrail(event, client, catalog, path));
	return {
		namespace,
		sharePath: sharePath(namespace.share_root, getConfig().mountPrefix, namespace.disk_path),
		trail
	};
}) satisfies LayoutServerLoad;
