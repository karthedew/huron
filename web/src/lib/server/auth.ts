import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import { env } from '$env/dynamic/private';
import type { Cookies } from '@sveltejs/kit';

export const PREVIEW_SESSION_COOKIE = 'huron_preview_session';
const PREVIEW_SESSION_SECRET = env.HURON_PREVIEW_SESSION_SECRET ?? randomUUID();

export function hasPreviewSession(cookies: Cookies): boolean {
	const value = cookies.get(PREVIEW_SESSION_COOKIE);
	if (!value) return false;
	const [nonce, signature] = value.split('.');
	if (!nonce || !signature) return false;
	const expected = sign(nonce);
	return (
		signature.length === expected.length &&
		timingSafeEqual(Buffer.from(signature), Buffer.from(expected))
	);
}

export function createPreviewSession(cookies: Cookies, secure: boolean): void {
	const nonce = randomUUID();
	cookies.set(PREVIEW_SESSION_COOKIE, `${nonce}.${sign(nonce)}`, {
		httpOnly: true,
		maxAge: 60 * 60 * 8,
		path: '/',
		sameSite: 'lax',
		secure
	});
}

export function clearPreviewSession(cookies: Cookies): void {
	cookies.delete(PREVIEW_SESSION_COOKIE, { path: '/' });
}

export function safeReturnTo(value: string | null | undefined): string {
	if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\'))
		return '/';
	return value;
}

function sign(value: string): string {
	return createHmac('sha256', PREVIEW_SESSION_SECRET).update(value).digest('base64url');
}
