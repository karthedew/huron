import { json } from '@sveltejs/kit';
import { isLevelParent } from '$lib/explorer';
import { loadLevel } from '$lib/server/explorer';
import { api, failureJson, failureResponse } from '$lib/server/guard';
import type { RequestHandler } from './$types';

/**
 * One level of the explorer as JSON, for its script: `?parent=` names the namespace, empty or
 * absent for the catalog root. The hook already answers a script without a session with a
 * 401; an API failure becomes a small JSON error, never the API's own answer or headers.
 */
export const GET: RequestHandler = async (event) => {
	const parent = event.url.searchParams.get('parent') ?? '';
	if (!isLevelParent(parent)) return failureJson(400, { code: 'BAD_REQUEST' });
	const client = api(event);
	try {
		const level = await loadLevel(client, event.params.catalog, parent);
		return json(level, { headers: { 'cache-control': 'private, no-store' } });
	} catch (failure) {
		return failureResponse(event, failure);
	}
};
