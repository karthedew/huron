import { error } from '@sveltejs/kit';
import { getProject, listDatasets, NotFound } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => {
	try {
		const project = await getProject(params.org, params.project);
		return { project, datasets: (await listDatasets(params.org, params.project)).items };
	} catch (e) {
		if (e instanceof NotFound) error(404, 'Not found');
		throw e;
	}
};
