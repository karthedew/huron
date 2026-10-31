import { error, redirect } from '@sveltejs/kit';
import type { Collection } from '$api/types';
import { LINKED_COLLECTION_GONE, errorCopy } from '$lib/error-copy';
import { identifierInCatalog } from '$lib/explorer';
import { api, fail, type GuardEvent } from '$lib/server/guard';
import { HuronApiError } from '$lib/server/huron-api';
import type { PageServerLoad } from './$types';

/**
 * A collection by its id, as activity entries that name no identifier link to it: on to its
 * page, which is addressed by identifier. A link may outlive its collection, so one the API does
 * not show says it may have been deleted. The page never renders anything itself.
 */
export const load = (async (event) => {
	const collection = await linked(event, api(event).collection(event.params.id));
	const { catalog, identifier } = collection;
	redirect(303, `/catalogs/${catalog}/collections/${identifierInCatalog(identifier)}`);
}) satisfies PageServerLoad;

async function linked(event: GuardEvent, read: Promise<Collection>): Promise<Collection> {
	try {
		return await read;
	} catch (failure) {
		if (failure instanceof HuronApiError && (failure.status === 403 || failure.status === 404)) {
			const code = LINKED_COLLECTION_GONE;
			error(404, { message: errorCopy(404, code).heading, code });
		}
		fail(event, failure);
	}
}
