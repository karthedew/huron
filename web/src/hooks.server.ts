import { error as httpError, json, redirect, type Handle } from '@sveltejs/kit';
import { clearHuronSession, getHuronSession, safeReturnTo } from '$lib/server/auth';
import { accountStore } from '$lib/server/huron-accounts';
import { organizationStore } from '$lib/server/huron-organizations';
import { selectOrganization } from '$lib/server/organization-context';
import { PolarisApiError } from '$lib/server/polaris-client';
import { polarisSettings } from '$lib/server/polaris-settings';

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
	event.locals.polaris = null;
	event.locals.organization = null;
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

	if (user && !PUBLIC_ROUTES.has(pathname)) {
		try {
			const organizations = await organizationStore().list(user);
			const organization = selectOrganization(
				organizations,
				event.url.searchParams.get('organization'),
				event.cookies.get('huron_organization')
			);
			if (rawApi && !event.url.searchParams.get('organization'))
				throw new PolarisApiError(400, 'Choose an organization for this Raw request.');
			event.locals.organization = organization;
			const realm = organization?.realm ?? polarisSettings().realm;
			if (user.isAdmin) await accountStore().ensureRealmIdentity(user.id, realm);
			event.locals.polaris = await accountStore().polarisClient(user.id, realm);
			if (organization && !rawApi && event.request.method === 'GET')
				event.cookies.set('huron_organization', organization.slug, {
					path: '/',
					httpOnly: true,
					sameSite: 'lax',
					secure: event.url.protocol === 'https:'
				});
		} catch (failure) {
			const status = failure instanceof PolarisApiError ? failure.status : 503;
			const message =
				failure instanceof PolarisApiError
					? failure.message
					: 'Unable to connect to this organization’s Polaris realm.';
			if (rawApi)
				return json(
					{
						message,
						...(event.url.pathname === '/ingestion/api/uploads' ? { uploadNotStarted: true } : {})
					},
					{ status }
				);
			httpError(status, message);
		}
	}
	return resolve(event);
};
