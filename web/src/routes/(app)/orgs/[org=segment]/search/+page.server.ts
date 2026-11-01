import { redirect } from '@sveltejs/kit';
import { legacySearchHref } from '$lib/search-links';
import type { PageServerLoad } from './$types';

/** Keep saved search addresses working through the central Search page. */
export const load = (async (event) => {
	redirect(303, legacySearchHref(event.url.searchParams, { organization: event.params.org }));
}) satisfies PageServerLoad;
