import { error } from '@sveltejs/kit';
import { getRelease, listRevisions, NotFound } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => {
	try {
		const release = await getRelease(params.org, params.project, params.dataset, params.release);
		return { release, revisions: (await listRevisions(params.release)).items };
	} catch (e) {
		if (e instanceof NotFound) error(404, 'Not found');
		throw e;
	}
};
