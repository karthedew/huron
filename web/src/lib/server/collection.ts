import type { Collection, JsonSchemaDocument } from '$api/types';
import { hasInexactIntegers } from '../json';
import { api, fail, guarded, type GuardEvent } from './guard';
import { HuronApiError, type HuronApi } from './huron-api';

/** A request for a collection's page: its catalog and its identifier within the catalog. */
export interface CollectionEvent extends GuardEvent {
	params: { catalog: string; identifier: string };
}

/**
 * The collection a page names, or the page outcome of its read: one the user may not see is
 * concealed by the API as not found, a draft too for readers. Every load of a collection's pages
 * reads it; the request's client shares the read with the collection layout's.
 */
export function pageCollection(event: CollectionEvent): Promise<Collection> {
	const { catalog, identifier } = event.params;
	return guarded(event, api(event).collectionByIdentifier(catalog, identifier));
}

/**
 * The schema a collection's metadata validates against, or `null` when it cannot be resolved:
 * the API refuses a schema override that no longer fits the catalog's schema, which a later
 * schema assignment can bring about. Other failures are the page's.
 */
export async function resolvedSchema(
	event: GuardEvent,
	client: HuronApi,
	id: string
): Promise<JsonSchemaDocument | null> {
	try {
		return await client.collectionSchema(id);
	} catch (failure) {
		if (isIncompatible(failure)) return null;
		fail(event, failure);
	}
}

/**
 * A collection's schema override with the digits the API wrote, for the Schema tab, which shows
 * them. Collections are parsed plainly (see `parseJson` in `./json`), which rounds an integer
 * past 2^53, so an override that may hold one is read once more, exactly; any other override is
 * the collection's own.
 */
export async function exactOverride(
	event: GuardEvent,
	client: HuronApi,
	collection: Collection
): Promise<Collection['schema_override']> {
	const override = collection.schema_override;
	if (override === null || !hasInexactIntegers(override)) return override;
	const exact = await guarded(event, client.collection(collection.id, { exact: true }));
	return exact.schema_override;
}

function isIncompatible(failure: unknown): boolean {
	return (
		failure instanceof HuronApiError &&
		failure.status === 422 &&
		failure.code === 'SCHEMA_INCOMPATIBLE'
	);
}
