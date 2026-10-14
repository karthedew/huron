import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url, locals }) => {
	const query = new URLSearchParams();
	for (const key of ['organization', 'catalog', 'namespace']) {
		const value = url.searchParams.get(key);
		if (value) query.set(key, value);
	}
	if (!query.has('organization') && locals.organization)
		query.set('organization', locals.organization.slug);
	redirect(303, `/browse${query.size ? '?' + query : ''}`);
};
