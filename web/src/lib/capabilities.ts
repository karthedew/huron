import type { Catalog, RoleGrant } from '$api/types';
import type { Named } from './names';
import { visibleOrganization } from './organizations';

/** What the signed-in user could change with the CLI. Hints only: the API enforces everything. */
export interface Capabilities {
	contribute: boolean;
	administerCatalog: boolean;
	administerOrganization: boolean;
	platformAdmin: boolean;
}

export interface CapabilityScope {
	/** The catalog's id. */
	catalogId?: string;
	/** The id of the organization (of the catalog), looked up in the visible organizations. */
	organizationId?: string;
}

/**
 * Capabilities from the user's roles (`whoami`). Each role includes the ones below it:
 * `platform_admin` everything, `org_admin` its organization's catalogs, `catalog_admin` and
 * `contributor` one catalog.
 */
export function capabilities(
	roles: readonly RoleGrant[],
	{ catalogId, organizationId }: CapabilityScope = {}
): Capabilities {
	const holds = (role: string, scope: string, scopeId?: string) =>
		roles.some(
			(grant) =>
				grant.role === role &&
				grant.scope === scope &&
				(scope === 'platform' || (scopeId !== undefined && grant.scope_id === scopeId))
		);
	const platformAdmin = holds('platform_admin', 'platform');
	const administerOrganization =
		platformAdmin || holds('org_admin', 'organization', organizationId);
	const administerCatalog = administerOrganization || holds('catalog_admin', 'catalog', catalogId);
	const contribute = administerCatalog || holds('contributor', 'catalog', catalogId);
	return { contribute, administerCatalog, administerOrganization, platformAdmin };
}

/**
 * The capabilities of the user's roles in a catalog: its own id, and its organization's, looked
 * up by name among the organizations the user can see (an organization admin of one they cannot
 * see is none of its).
 */
export function catalogCapabilities(
	roles: readonly RoleGrant[],
	catalog: Pick<Catalog, 'id' | 'organization'>,
	organizations: ReadonlyArray<Named & { id: string }>
): Capabilities {
	const owner = visibleOrganization(catalog.organization, organizations);
	return capabilities(roles, { catalogId: catalog.id, organizationId: owner?.id });
}
