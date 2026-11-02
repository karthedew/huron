import { ROLES, ROLE_SCOPES, type GrantSource, type Role, type RoleScope } from '$api/types';

/** The groups holding one role on a catalog through one scope's grant. */
export interface AccessSource {
	scope: RoleScope;
	/** In the API's order (by group); never empty. */
	groups: string[];
}

/** The groups holding one role on a catalog, by where each was granted. */
export interface RoleAccess {
	role: Role;
	/**
	 * Platform, then organization, then catalog, leaving out the scopes that grant the role to no
	 * group. A group granted both on the organization and on the catalog is under both: revoking
	 * it on the catalog leaves it the role through the organization.
	 */
	sources: AccessSource[];
}

/**
 * The catalog's grant sources (`GET /catalogs/{c}/grants/sources`) per role, strongest role
 * first, every role present even when no group holds it.
 */
export function catalogAccess(sources: readonly GrantSource[]): RoleAccess[] {
	return ROLES.map((role) => ({
		role,
		sources: ROLE_SCOPES.map((scope) => ({
			scope,
			groups: sources
				.filter((source) => source.role === role && source.scope === scope)
				.map(({ group }) => group)
		})).filter(({ groups }) => groups.length > 0)
	}));
}
