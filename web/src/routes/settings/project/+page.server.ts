import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = ({ url }) => {
	const query = new URLSearchParams();
	for (const key of ['catalog', 'namespace']) {
		const value = url.searchParams.get(key);
		if (value) query.set(key, value);
	}
	redirect(303, `/browse${query.size ? '?' + query : ''}`);
};
