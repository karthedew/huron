import { getProject, listProjectPermissions } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => ({
	project: await getProject('example-org', 'example-study'),
	permissions: (await listProjectPermissions('example-org', 'example-study')).items
});
