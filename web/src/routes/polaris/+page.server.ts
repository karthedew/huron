import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

/** Preserve links while making the main Huron surfaces authoritative. */
export const load: PageServerLoad = ({ url, locals }) => {
	const query = new URLSearchParams(url.search);
	const access = query.get('tab') === 'access';
	query.delete('tab');
	const path = access ? '/settings/catalog' : '/browse';
	if (!query.has('organization') && locals.organization)
		query.set('organization', locals.organization.slug);
	redirect(303, `${path}${query.size ? '?' + query : ''}`);
};
