import type { HuronOrganizationSummary } from '$api/types';
import { PolarisApiError } from './polaris-client';

/** Explicit URLs win over the convenience cookie, including across concurrent browser tabs. */
export function selectOrganization(
	organizations: HuronOrganizationSummary[],
	requested: string | null,
	remembered: string | undefined
): HuronOrganizationSummary | null {
	if (requested !== null) {
		const organization = organizations.find((entry) => entry.slug === requested);
		if (!organization) throw new PolarisApiError(404);
		return organization;
	}
	return organizations.find((entry) => entry.slug === remembered) ?? organizations[0] ?? null;
}
