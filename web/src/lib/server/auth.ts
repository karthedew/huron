import { randomBytes } from 'node:crypto';
import type { Cookies } from '@sveltejs/kit';
import type { HuronUser } from '$api/types';
import type { AuthenticatedAccount } from './huron-accounts';
import type { PolarisClient } from './polaris-client';

export const HURON_SESSION_COOKIE = 'huron_session';
const SESSION_DURATION = 8 * 60 * 60 * 1000;

interface HuronSession {
	user: HuronUser;
	client: PolarisClient;
	clientId: string;
	authVersion: number;
	expiresAt: number;
	notice?: string;
}

const sessions = new Map<string, HuronSession>();

export function getHuronSession(cookies: Cookies): HuronSession | undefined {
	const now = Date.now();
	for (const [id, session] of sessions) if (session.expiresAt <= now) sessions.delete(id);
	const id = cookies.get(HURON_SESSION_COOKIE);
	return id ? sessions.get(id) : undefined;
}

export function createHuronSession(
	cookies: Cookies,
	account: AuthenticatedAccount,
	secure: boolean
): void {
	clearHuronSession(cookies);
	const id = randomBytes(32).toString('base64url');
	sessions.set(id, { ...account, expiresAt: Date.now() + SESSION_DURATION });
	cookies.set(HURON_SESSION_COOKIE, id, {
		httpOnly: true,
		maxAge: SESSION_DURATION / 1000,
		path: '/',
		sameSite: 'lax',
		secure
	});
}

export function clearHuronSession(cookies: Cookies): void {
	const id = cookies.get(HURON_SESSION_COOKIE);
	if (id) sessions.delete(id);
	cookies.delete(HURON_SESSION_COOKIE, { path: '/' });
	// Retire cookies left by the former preview and manual Polaris login.
	cookies.delete('huron_preview_session', { path: '/' });
	cookies.delete('huron_polaris_session', { path: '/' });
}

export function safeReturnTo(value: string | null | undefined): string {
	if (
		!value ||
		!value.startsWith('/') ||
		value.startsWith('//') ||
		value.includes('\\') ||
		/[\x00-\x1f\x7f]/.test(value)
	)
		return '/';
	return value;
}
