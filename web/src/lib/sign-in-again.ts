import { resolve } from '$app/paths';

/** The login page after a session ended; signing in again returns to `returnTo`. */
export function expiredLoginPath(returnTo: string): string {
	return `${resolve('/login')}?status=expired&returnTo=${encodeURIComponent(returnTo)}`;
}

/**
 * Leave for the login page because the session ended, to come back to this page. For scripts
 * whose request the server refused with a 401; page loads get the server's redirect instead.
 */
export function signInAgain(): void {
	location.assign(expiredLoginPath(location.pathname + location.search));
}
