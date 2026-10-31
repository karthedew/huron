import { error } from '@sveltejs/kit';
import { FAILURE_COPY, api, fail, type GuardEvent } from '$lib/server/guard';
import { HuronApiError } from '$lib/server/huron-api';
import type { RequestHandler } from './$types';

/**
 * The `metadata.json` the CLI writes beside a collection's files, byte for byte, shown inline
 * as JSON. The answer is built here, never the API's own, and sandboxed: it is the
 * contributors' text. A draft has no such file: like a collection the user may not see, it is
 * not found.
 */
export const GET: RequestHandler = async (event) => {
	const client = api(event);
	const { catalog, identifier } = event.params;
	const collection = await read(event, client.collectionByIdentifier(catalog, identifier));
	if (collection.state === 'draft') error(404, { message: FAILURE_COPY.notFound });
	const body = await read(event, client.collectionSidecar(collection.id));
	return new Response(body, {
		headers: {
			'content-type': 'application/json',
			'content-disposition': 'inline',
			'content-security-policy': "default-src 'none'; sandbox",
			'cache-control': 'private, no-store'
		}
	});
};

/** An API read whose 404, or 409 (no `metadata.json` for a draft), is this file's 404. */
async function read<T>(event: GuardEvent, answer: Promise<T>): Promise<T> {
	try {
		return await answer;
	} catch (failure) {
		if (failure instanceof HuronApiError && (failure.status === 404 || failure.status === 409)) {
			error(404, { message: FAILURE_COPY.notFound, code: failure.code });
		}
		fail(event, failure);
	}
}
