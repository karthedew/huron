import type { LayoutServerLoad } from './$types';
import { error as httpError } from '@sveltejs/kit';
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
	const requestedOrganization = url.searchParams.get('organization');
	const requestedCatalog = url.searchParams.get('catalog');
	const organization = requestedOrganization
		? organizations.find((entry) => entry.slug === requestedOrganization)
		: (organizations.find((entry) => entry.catalogNames.includes(requestedCatalog ?? '')) ??
			organizations[0]);
	if (locals.user && !catalogError && requestedOrganization && !organization)
		httpError(404, 'Not found');
	const catalogs = visibleCatalogs.filter((catalog) =>
		organization?.catalogNames.includes(catalog.name)
	);
	if (
		locals.user &&
		!catalogError &&
		requestedOrganization &&
		requestedCatalog &&
		!catalogs.some((catalog) => catalog.name === requestedCatalog)
	)
		httpError(404, 'Not found');
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
