import { metadataView, problemRows } from '$lib/metadata';
import { pageCollection, resolvedSchema } from '$lib/server/collection';
import { api } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * A collection's metadata against its resolved schema, and what keeps a draft or an incomplete
 * collection from being valid, each problem with the field it is about. Both leave as views of
 * plain values, shortened where they are long; the metadata itself stays here (see
 * `MetadataView`).
 */
export const load = (async (event) => {
	const collection = await pageCollection(event);
	const schema = await resolvedSchema(event, api(event), collection.id);
	return {
		metadata: metadataView(collection.metadata, schema),
		problems: problemRows(collection.problems, schema, collection.metadata),
		schemaResolved: schema !== null
	};
}) satisfies PageServerLoad;
