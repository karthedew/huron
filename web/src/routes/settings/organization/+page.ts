import { getOrganization, listOrganizationMembers, listOrganizationPermissions } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => ({
	organization: await getOrganization('example-org'),
	members: (await listOrganizationMembers('example-org')).items,
	permissions: (await listOrganizationPermissions('example-org')).items
});
