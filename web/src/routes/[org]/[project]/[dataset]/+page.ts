import { error } from '@sveltejs/kit';
import { getDataset, listReleases, NotFound } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => {
	try {
		const dataset = await getDataset(params.org, params.project, params.dataset);
		return {
			dataset,
			releases: (await listReleases(params.org, params.project, params.dataset)).items
		};
	} catch (e) {
		if (e instanceof NotFound) error(404, 'Not found');
		throw e;
	}
};
