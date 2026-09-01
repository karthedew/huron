import { getWhoAmI, listApiKeys } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ url }) => {
	const requestedTab = url.searchParams.get('tab');
	return {
		whoami: await getWhoAmI(),
		keys: (await listApiKeys()).items,
		initialTab: ['profile', 'preferences', 'api-keys', 'access'].includes(requestedTab ?? '')
			? requestedTab
			: 'profile'
	};
};
