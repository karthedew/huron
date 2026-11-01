import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/** Only the presence of validation problems is needed to choose CLI actions. */
export const load = (async (event) => {
	const collection = await guarded(
		event,
		api(event).collectionByIdentifier(event.params.catalog, event.params.identifier)
	);
	return { hasProblems: collection.problems.length > 0 };
}) satisfies PageServerLoad;
