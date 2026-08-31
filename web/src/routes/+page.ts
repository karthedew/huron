import { search } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ url }) => {
	const q = url.searchParams.get('q') ?? '';
	return { q, results: await search(q || 'recent') };
};
