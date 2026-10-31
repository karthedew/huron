import { randomUUID } from 'node:crypto';
import { error, json, redirect, type Handle, type HandleServerError } from '@sveltejs/kit';
import { dev } from '$app/environment';
import { ConfigError, getConfig, publicOrigin, type Config } from '$lib/server/config';
import { CookieJar } from '$lib/server/cookies';
import { loginPath, safeReturnTo } from '$lib/server/return-to';
import { sessionStore } from '$lib/server/sessions';

/** Paths that answer without a session; everything else requires one. */
const PUBLIC_PATHS: ReadonlySet<string> = new Set([
	'/login',
	'/auth/login',
	'/auth/callback',
	'/logout',
	'/healthz'
]);

/** Sign-in and logout answers carry session cookies; they must never be stored. */
const NO_STORE_PATHS: ReadonlySet<string> = new Set(['/auth/login', '/auth/callback', '/logout']);

/** The header the explorer's tree fetch sends; such requests get JSON instead of a redirect. */
const PROGRAMMATIC_HEADER = 'x-huron-fetch';

export const handle: Handle = async ({ event, resolve }) => {
	const origin = publicOrigin(configuration(), event.url);
	const jar = new CookieJar(event.cookies, origin);
	const sessionId = jar.session();
	const user = sessionId === undefined ? undefined : sessionStore().user(sessionId);
	event.locals.user = user ?? null;
	if (sessionId !== undefined && user === undefined) jar.deleteSession();

	const { pathname, search } = event.url;
	const noStore = user !== undefined || NO_STORE_PATHS.has(pathname);
	if (user === undefined && !PUBLIC_PATHS.has(pathname)) {
		if (event.request.headers.get(PROGRAMMATIC_HEADER) === '1') {
			const response = json({ code: 'UNAUTHENTICATED' }, { status: 401 });
			if (sessionId !== undefined) {
				response.headers.append('set-cookie', jar.sessionDeletionHeader());
			}
			return withSecurityHeaders(response, true);
		}
		// Thrown, not returned: SvelteKit then answers data and action requests in their own
		// redirect format and applies the cookie deletion above. The bodiless same-origin 303
		// carries no security headers as a result, which it does not need.
		redirect(
			303,
			loginPath({
				returnTo: safeReturnTo(pathname + search, origin),
				status: sessionId === undefined ? undefined : 'expired'
			})
		);
	}

	let response: Response | undefined;
	try {
		response = await resolve(event);
		return response;
	} finally {
		if (response !== undefined) withSecurityHeaders(response, noStore);
	}
};

export const handleError: HandleServerError = ({ error: failure, event, status, message }) => {
	// SvelteKit reports its own client errors here too, such as a 404 for a path no route
	// matches. They are no failure of this server: no log entry and no reference to quote.
	if (status < 500) return { message };
	const id = randomUUID();
	// The class only: the message of an unexpected error is free text that may quote its input,
	// such as a token that failed to parse.
	const cause = failure instanceof Error ? failure.name : typeof failure;
	console.error('huron-web request failed', {
		id,
		status,
		path: event.url.pathname,
		message,
		cause
	});
	if (dev && failure instanceof Error) console.error(failure.stack);
	return { message, id };
};

/** The settings, or a 500 whose message names the broken variable (never its value). */
function configuration(): Config {
	try {
		return getConfig();
	} catch (failure) {
		if (failure instanceof ConfigError) {
			console.error(`huron-web configuration: ${failure.message}`);
			error(500, { message: failure.message, code: 'CONFIG' });
		}
		throw failure;
	}
}

function withSecurityHeaders(response: Response, noStore: boolean): Response {
	response.headers.set('x-content-type-options', 'nosniff');
	response.headers.set('x-frame-options', 'DENY');
	response.headers.set('referrer-policy', 'same-origin');
	if (noStore) response.headers.set('cache-control', 'private, no-store');
	return response;
}
