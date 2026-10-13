import { error, redirect, type RequestEvent } from '@sveltejs/kit';
import type { HuronUser } from '$api/types';
import { safeReturnTo } from './auth';
import type { PolarisClient } from './polaris-client';

export function getAuthenticatedPolaris(
	event: Pick<RequestEvent, 'locals' | 'url'>
): PolarisClient {
	if (!event.locals.user || event.locals.user.disabled || !event.locals.polaris) {
		const returnTo = safeReturnTo(event.url.pathname + event.url.search);
		redirect(303, `/login?returnTo=${encodeURIComponent(returnTo)}`);
	}
	return event.locals.polaris;
}

export function requireAdmin(event: Pick<RequestEvent, 'locals' | 'url'>): HuronUser {
	getAuthenticatedPolaris(event);
	if (!event.locals.user?.isAdmin) error(403, 'Huron administrator access is required.');
	return event.locals.user;
}

export const requireHuronAdmin = requireAdmin;
