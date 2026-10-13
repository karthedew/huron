import type { PageServerLoad } from './$types';
import { searchCatalogs } from '$lib/server/polaris-browse';

export const load: PageServerLoad = async ({ parent, url }) => {
	const { catalogs } = await parent();
	const q = (url.searchParams.get('q') ?? '').trim();
	return { q, catalogs: searchCatalogs(catalogs, q) };
};
