import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

/** Preserve links while making the main Huron surfaces authoritative. */
export const load: PageServerLoad = ({ url }) => {
	const query = new URLSearchParams(url.search);
	const access = query.get('tab') === 'access';
	query.delete('tab');
	const path = access ? '/settings/catalog' : '/browse';
	redirect(303, `${path}${query.size ? '?' + query : ''}`);
};
