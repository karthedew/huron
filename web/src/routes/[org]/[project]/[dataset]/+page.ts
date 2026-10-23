import { error } from '@sveltejs/kit';
import { getDataset, NotFound } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => {
	try {
		return { dataset: await getDataset(params.org, params.project, params.dataset) };
	} catch (e) {
		if (e instanceof NotFound) error(404, 'Not found');
		throw e;
	}
};
