import { redirect, type Handle } from '@sveltejs/kit';
import { hasPreviewSession, safeReturnTo } from '$lib/server/auth';

const PUBLIC_ROUTES = new Set(['/login', '/logout', '/signup']);

export const handle: Handle = async ({ event, resolve }) => {
	const pathname = event.url.pathname;
	const authenticated = hasPreviewSession(event.cookies);

	if (!authenticated && !PUBLIC_ROUTES.has(pathname)) {
		const returnTo = safeReturnTo(`${pathname}${event.url.search}`);
		redirect(303, `/login?returnTo=${encodeURIComponent(returnTo)}`);
	}

	if (authenticated && (pathname === '/login' || pathname === '/signup')) {
		redirect(303, safeReturnTo(event.url.searchParams.get('returnTo')));
	}

	return resolve(event);
};
