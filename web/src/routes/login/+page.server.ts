import { redirect } from '@sveltejs/kit';
import { getConfig, publicOrigin } from '$lib/server/config';
import { SIGN_IN_ERROR_CODES } from '$lib/server/oidc';
import { safeReturnTo } from '$lib/server/return-to';
import type { PageServerLoad } from './$types';

const STATUSES = ['signed-out', 'expired'] as const;

export const load = (({ locals, url }) => {
	const returnTo = safeReturnTo(url.searchParams.get('returnTo'), publicOrigin(getConfig(), url));
	if (locals.user !== null) redirect(303, returnTo);
	return {
		returnTo,
		status: known(STATUSES, url.searchParams.get('status')),
		error: known(SIGN_IN_ERROR_CODES, url.searchParams.get('error'))
	};
}) satisfies PageServerLoad;

/** The value when it is one of `codes`; query text is never echoed otherwise. */
function known<T extends string>(codes: readonly T[], value: string | null): T | null {
	return codes.find((code) => code === value) ?? null;
}
