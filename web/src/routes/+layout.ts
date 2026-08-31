import { getWhoAmI, listOrganizations } from '$api/client';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async () => ({
	organizations: (await listOrganizations()).items,
	user: await getWhoAmI()
});
