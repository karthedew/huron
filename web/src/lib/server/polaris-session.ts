import type { Cookies } from '@sveltejs/kit';
import { getHuronSession } from './auth';
import { PolarisApiError, type PolarisClient } from './polaris-client';

export { polarisSettings } from './polaris-settings';

export function hasPolarisSession(cookies: Cookies): boolean {
	return getHuronSession(cookies) !== undefined;
}

export function polarisSessionIdentity(cookies: Cookies): { clientId: string } | null {
	const session = getHuronSession(cookies);
	return session ? { clientId: session.clientId } : null;
}

export function getPolarisClient(cookies: Cookies): PolarisClient {
	const session = getHuronSession(cookies);
	if (!session) throw new PolarisApiError(401, 'Sign in to Huron to continue.');
	return session.client;
}

export function queuePolarisNotice(cookies: Cookies, message: string): void {
	const session = getHuronSession(cookies);
	if (session) session.notice = message;
}

export function consumePolarisNotice(cookies: Cookies): string | null {
	const session = getHuronSession(cookies);
	const message = session?.notice ?? null;
	if (session) delete session.notice;
	return message;
}
