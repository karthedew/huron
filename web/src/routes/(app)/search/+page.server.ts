import { redirect } from '@sveltejs/kit';
import { ORGANIZATION_LIMIT, shellOrganization } from '$lib/organizations';
import { JSON_LABEL, emptySearch, readSearch } from '$lib/search';
import { requestCookies } from '$lib/server/cookies';
import { api, guarded } from '$lib/server/guard';
import type { PageServerLoad } from './$types';

/**
 * `/search`, where the shell's search box leads without a catalog or an organization: which
 * organization to search, for the text and label filters of the address, read and checked as a
 * search reads them (see `readSearch`). What fails that check is left out of the links, and the
 * page says why. A user with one organization goes straight to its search, the address's text
 * and filters as they were written, so that its form explains anything wrong with them; one with
 * none learns why. States are left out: each catalog decides who sees its drafts.
 */
export const load = (async (event) => {
	const organizations = await guarded(
		event,
		api(event).organizations({ limit: ORGANIZATION_LIMIT })
	);
	const params = event.url.searchParams;
	const list = organizations.items;
	if (list.length === 1 && !organizations.next_cursor) {
		redirect(303, `/orgs/${encodeURIComponent(list[0].name)}/search${searchedFor(params)}`);
	}
	const { search, errors } = readSearch(params, { drafts: false });
	return {
		organization: requestCookies(event).rememberedOrganization(),
		// Names only: the page links each organization, up to 500 of them.
		organizationList: list.map(shellOrganization),
		search: { ...emptySearch(), q: errors.q === null ? search.q : '', labels: search.labels },
		errors
	};
}) satisfies PageServerLoad;

/** The text and label filters of an address, as written, for another search page. */
function searchedFor(params: URLSearchParams): string {
	const kept = new URLSearchParams();
	for (const [name, value] of params) {
		if (name === 'q' || name === 'label' || name === JSON_LABEL) kept.append(name, value);
	}
	const query = kept.toString();
	return query === '' ? '' : `?${query}`;
}
