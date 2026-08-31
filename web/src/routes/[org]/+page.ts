import { error } from '@sveltejs/kit';
import { getOrganization, listProjects, NotFound } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => {
	try {
		const organization = await getOrganization(params.org);
		return { organization, projects: (await listProjects(params.org)).items };
	} catch (e) {
		if (e instanceof NotFound) error(404, 'Not found');
		throw e;
	}
};
