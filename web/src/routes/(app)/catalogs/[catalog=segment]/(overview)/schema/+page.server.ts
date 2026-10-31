import { schemaView } from '$lib/schema-view';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * The catalog's schema, resolved along its `extends` chain: what its metadata must satisfy. It
 * leaves as its table and its JSON text, never as the document (see `SchemaView`).
 */
export const load = (async (event) => {
	const document = await guarded(event, api(event).catalogSchema(event.params.catalog));
	return { schema: schemaView(document) };
}) satisfies PageServerLoad;
