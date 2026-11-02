import type { Organization } from '$api/types';
import type { Named } from './names';

/**
 * How many organizations the shell reads on every page, in one page: enough for any switcher.
 * Loads that need the list read it so too, sharing the shell's read within a request.
 */
export const ORGANIZATION_LIMIT = 500;

/**
 * An organization as the shell carries it on every page: what names it, and its id, which
 * decides a catalog's capabilities. Its description, counts and dates stay with the pages that
 * show them: the shell's list holds up to `ORGANIZATION_LIMIT` organizations, in every page's
 * data.
 */
export type ShellOrganization = Pick<Organization, 'id' | 'name' | 'display_name'>;

/** The part of an organization the shell keeps. */
export function shellOrganization({ id, name, display_name }: Organization): ShellOrganization {
	return { id, name, display_name };
}

/**
 * The organization of that name when the user can see it. `page.data.organization` and the
 * remembered cookie are only names; the shell trusts them once they match a visible one.
 */
export function visibleOrganization<T extends Named>(
	name: string | null | undefined,
	organizations: readonly T[]
): T | null {
	if (!name) return null;
	return organizations.find((organization) => organization.name === name) ?? null;
}

/** Where "Back to …" leads: the current organization, else the only one the user can see. */
export function homeOrganization<T extends Named>(
	current: T | null,
	organizations: readonly T[]
): T | null {
	return current ?? (organizations.length === 1 ? organizations[0] : null);
}
