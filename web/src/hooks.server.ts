import { json, redirect, type Handle } from '@sveltejs/kit';
import { clearHuronSession, getHuronSession, safeReturnTo } from '$lib/server/auth';
import { accountStore } from '$lib/server/huron-accounts';

const PUBLIC_ROUTES = new Set(['/login', '/logout', '/signup']);
const WORKSPACE_ROUTES = new Set([
	'/',
	'/browse',
	'/admin',
	'/settings/organization',
	'/settings/catalog',
	'/settings/project',
	'/account',
	'/ingestion',
	'/polaris'
]);

export const handle: Handle = async ({ event, resolve }) => {
	const pathname = event.url.pathname;
	const rawApi = pathname.startsWith('/ingestion/api/');
	const session = getHuronSession(event.cookies);
	const user = session
		? await accountStore().sessionUser(session.user.id, session.authVersion)
		: null;
	event.locals.user = user;
	event.locals.polaris = user && session ? session.client : null;
	if (session && !user) clearHuronSession(event.cookies);
	const authenticated = user !== null;

	if (!authenticated && !PUBLIC_ROUTES.has(pathname)) {
		if (rawApi) return json({ message: 'Sign in to Huron to continue.' }, { status: 401 });
		const returnTo = safeReturnTo(`${pathname}${event.url.search}`);
		redirect(303, `/login?returnTo=${encodeURIComponent(returnTo)}`);
	}

	if (authenticated && (pathname === '/login' || pathname === '/signup')) {
		redirect(303, safeReturnTo(event.url.searchParams.get('returnTo')));
	}
	if (rawApi && !['GET', 'HEAD', 'OPTIONS'].includes(event.request.method)) {
		if (event.request.headers.get('origin') !== event.url.origin)
			return json(
				{ message: 'The upload request must come from this Huron site.' },
				{ status: 403 }
			);
	}
	if (authenticated && !rawApi && !PUBLIC_ROUTES.has(pathname) && !WORKSPACE_ROUTES.has(pathname)) {
		redirect(303, '/browse');
	}

	return resolve(event);
};
