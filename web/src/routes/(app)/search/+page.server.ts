import { error } from '@sveltejs/kit';
import { match as segment } from '../../../params/segment';
import { ORGANIZATION_LIMIT, shellOrganization } from '$lib/organizations';
import { readSearch } from '$lib/search';
import { requestCookies } from '$lib/server/cookies';
import { api, guarded } from '$lib/server/guard';
import { searchCatalog } from '$lib/server/catalog-search';
import { organizationCatalogs } from '$lib/server/org-search';
import { searchOrganizationPage } from '$lib/server/organization-search';
import type { PageServerLoad } from './$types';

/** A single search workspace with an explicit organization and optional catalog. */
export const load = (async (event) => {
	const client = api(event);
	const params = event.url.searchParams;
	const requestedOrganization = scopeName(params, 'organization');
	const requestedCatalog = scopeName(params, 'catalog');
	const visible = await guarded(event, client.organizations({ limit: ORGANIZATION_LIMIT }));
	const catalog =
		requestedCatalog === null ? null : await guarded(event, client.catalog(requestedCatalog));
	if (
		catalog !== null &&
		requestedOrganization !== null &&
		catalog.organization !== requestedOrganization
	) {
		error(400, { message: 'Choose a catalog in the selected organization.' });
	}
	const remembered = requestCookies(event).rememberedOrganization();
	const organization =
		requestedOrganization ??
		catalog?.organization ??
		visible.items.find(({ name }) => name === remembered)?.name ??
		(visible.items.length > 0 ? visible.items[0].name : null);
	const organizationList = visible.items.map(shellOrganization);
	const moreOrganizations = visible.next_cursor !== null;
	const read = readSearch(params, { drafts: false });
	if (organization === null) {
		return {
			organization,
			organizationList,
			moreOrganizations,
			selectedOrganization: null,
			scope: null,
			search: read.search,
			catalogSearch: null,
			organizationSearch: null
		};
	}
	const selectedOrganization =
		visible.items.find(({ name }) => name === organization) ??
		(await guarded(event, client.organization(organization)));
	if (!organizationList.some(({ id }) => id === selectedOrganization.id)) {
		organizationList.push(shellOrganization(selectedOrganization));
	}
	const { catalogs, truncated } = await guarded(event, organizationCatalogs(client, organization));
	// A saved catalog link still works when its catalog falls beyond the first 50 choices.
	const choices =
		catalog !== null && !catalogs.some(({ name }) => name === catalog.name)
			? [...catalogs, catalog]
			: catalogs;
	const scope = {
		organization,
		catalog: catalog?.name ?? null,
		catalogs: choices.map(({ name, display_name }) => ({ name, display_name }))
	};
	const common = {
		organization,
		organizationList,
		moreOrganizations,
		selectedOrganization: shellOrganization(selectedOrganization),
		scope
	};
	if (catalog !== null) {
		const result = await searchCatalog({ ...event, params: { catalog: catalog.name } });
		return {
			...common,
			search: result.search,
			catalogSearch: { ...result, catalog, scope },
			organizationSearch: null
		};
	}
	const result = await searchOrganizationPage({ ...event, params: { org: organization } });
	return {
		...common,
		search: result.search,
		catalogSearch: null,
		organizationSearch: {
			...result,
			truncated,
			organizationDetails: shellOrganization(selectedOrganization),
			scope
		}
	};
}) satisfies PageServerLoad;

/** Validate scope selectors before sending their values to the API. */
function scopeName(params: URLSearchParams, key: string): string | null {
	const value = params.get(key);
	if (!value) return null;
	if (!segment(value)) error(400, { message: 'Choose a valid organization and catalog.' });
	return value;
}
