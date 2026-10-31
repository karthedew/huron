import type { Collection, RoleGrant } from '$api/types';
import { collectionSummary, type CollectionSummary } from '$lib/collections';
import type { ExplorerLevel } from '$lib/explorer';
import { catalogFixture, collectionFixture, organizationFixture } from './api-fixtures';
import { fakeUser } from './events';

/** The explorer's root of the fixture catalog: `solar-wind` and `fields`. */
export const ROOT_LEVEL: ExplorerLevel = {
	parent: '',
	namespaces: [
		{ name: 'fields', path: 'fields', empty: false },
		{ name: 'solar-wind', path: 'solar-wind', empty: false }
	],
	namespacesNext: null,
	collections: [],
	collectionsNext: null
};

/**
 * What a page of a catalog gets from the `(app)` and catalog layouts, for component tests;
 * pages add their own data on top.
 */
export function catalogPageData({
	roles = [],
	groups = ['helio-readers']
}: { roles?: RoleGrant[]; groups?: string[] } = {}) {
	return {
		user: fakeUser({ groups }),
		organizations: [organizationFixture()],
		organizationsUnavailable: false,
		roles,
		rolesUnavailable: false,
		rememberedOrganization: null,
		organization: 'helio',
		catalog: catalogFixture({ description: 'Solar wind, fields and energetic particles.' }),
		catalogs: [
			{ name: 'heliophysics', display_name: 'Heliophysics' },
			{ name: 'space-weather', display_name: 'Space Weather' }
		],
		moreCatalogs: false,
		root: ROOT_LEVEL
	};
}

/** A grant of a catalog role on the fixture catalog. */
export function catalogRole(role: string): RoleGrant {
	return { scope: 'catalog', scope_id: catalogFixture().id, role };
}

/** A collection of the fixture catalog as the collection layout gives it to its pages. */
export function collectionOf(overrides: Partial<Collection> = {}): CollectionSummary {
	return collectionSummary(collectionFixture(overrides), '/projects/huron');
}
