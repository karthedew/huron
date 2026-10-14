import type { LayoutServerLoad } from './$types';
import { PolarisApiError } from '$lib/server/polaris-client';
import { selectCatalog } from '$lib/stores/workspace';
import { organizationDirectory } from '$lib/server/huron-organizations';
import type { HuronOrganizationSummary, PolarisCatalog } from '$api/types';

export const load: LayoutServerLoad = async ({ locals, request, setHeaders, url }) => {
	if (request.method !== 'POST') setHeaders({ 'Cache-Control': 'private, no-store' });
	let organizations: HuronOrganizationSummary[] = [];
	let visibleCatalogs: PolarisCatalog[] = [];
	let catalogError: string | null = null;
	if (locals.polaris && locals.user) {
		try {
			const directory = await organizationDirectory(locals.user, locals.polaris);
			organizations = directory.organizations;
			visibleCatalogs = directory.catalogs;
		} catch (error) {
			catalogError =
				error instanceof PolarisApiError ? error.message : 'Unable to load Polaris catalogs.';
		}
	}
	const requestedCatalog = url.searchParams.get('catalog');
	const organization =
		organizations.find((entry) => entry.slug === locals.organization?.slug) ?? locals.organization;
	const catalogs = visibleCatalogs.filter((catalog) =>
		organization?.catalogNames.includes(catalog.name)
	);

	return {
		organizations,
		organization: organization ?? null,
		selectedOrganization: organization?.slug ?? '',
		catalogs,
		user: locals.user,
		selectedCatalog: selectCatalog(catalogs, requestedCatalog),
		catalogError
	};
};
