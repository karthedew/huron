import { isJsonDocument } from '$lib/json';
import { schemaView } from '$lib/schema-view';
import { exactOverride, pageCollection, resolvedSchema } from '$lib/server/collection';
import { api } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * What a collection's metadata must satisfy: the catalog's schema with the collection's own
 * schema override composed on top, and the override alone, when it has one. Both leave as their
 * tables and JSON text, never as documents (see `SchemaView`), with the digits the API wrote for
 * integers past 2^53. `schema` is `null` when the override no longer fits the catalog's schema.
 */
export const load = (async (event) => {
	const client = api(event);
	const collection = await pageCollection(event);
	const [resolved, own] = await Promise.all([
		resolvedSchema(event, client, collection.id),
		exactOverride(event, client, collection)
	]);
	const schema = resolved === null ? null : schemaView(resolved);
	const override = isJsonDocument(own) ? schemaView(own) : null;
	return {
		// Composed with an override, the document takes the override's title and description where
		// it sets them and the catalog schema's otherwise (`compose` in
		// src/huron/schema/composition.py), so they would introduce this table with the override's
		// name or the catalog schema's words. The section's heading says what the table holds.
		schema:
			schema !== null && override !== null ? { ...schema, title: null, description: null } : schema,
		override
	};
}) satisfies PageServerLoad;
