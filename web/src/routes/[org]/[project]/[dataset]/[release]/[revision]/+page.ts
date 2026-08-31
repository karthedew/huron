import { error } from '@sveltejs/kit';
import { getManifest, getRevision, NotFound } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params }) => {
	const number = Number(params.revision);
	if (!Number.isInteger(number)) error(404, 'Not found');
	try {
		return {
			revision: await getRevision(params.release, number),
			manifest: (await getManifest(params.release, number)).items,
			slugs: params
		};
	} catch (e) {
		if (e instanceof NotFound) error(404, 'Not found');
		throw e;
	}
};
