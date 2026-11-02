import { randomUUID } from 'node:crypto';
import { error, json, redirect, type Cookies } from '@sveltejs/kit';
import { errorCopy } from '../error-copy';
import { isCursorParameter } from '../paging';
import { getConfig, publicOrigin } from './config';
import { CookieJar } from './cookies';
import { HuronApi, HuronApiError } from './huron-api';
import { loginPath, safeReturnTo } from './return-to';
import { sessionStore, type SessionUser } from './sessions';

/** The part of a request event the guard needs. */
export interface GuardEvent {
	cookies: Cookies;
	locals: App.Locals;
	url: URL;
}

/**
 * Fixed copy for failed API reads, the headings the error pages show for the same statuses (an
 * endpoint's error shows on the static page, `src/error.html`); the API's `detail` and `context`
 * are never shown.
 */
export const FAILURE_COPY = {
	badRequest: errorCopy(400).heading,
	forbidden: errorCopy(403).heading,
	notFound: errorCopy(404).heading,
	unavailable: errorCopy(503).heading,
	internal: errorCopy(500).heading
} as const;

export type Settled<T> = { ok: true; value: T } | { ok: false; failure: unknown };

const clients = new WeakMap<App.Locals, HuronApi>();
/** The log reference of each failure already logged. */
const references = new WeakMap<HuronApiError, string>();

/**
 * The API client of this request, signed in as its user. GET answers are shared within the
 * request, so layouts and pages may ask for the same data without calling `parent()`.
 * Without a live session it throws the redirect to the login page.
 */
export function api(event: GuardEvent): HuronApi {
	const existing = clients.get(event.locals);
	if (existing !== undefined) return existing;
	const config = getConfig();
	const origin = publicOrigin(config, event.url);
	const sessionId = new CookieJar(event.cookies, origin).session();
	const token = sessionId === undefined ? undefined : sessionStore().token(sessionId);
	if (token === undefined) toLogin(event, origin, sessionId);
	const client = new HuronApi({
		baseUrl: config.apiUrl,
		token,
		timeoutMs: config.apiTimeoutMs,
		memoize: true
	});
	clients.set(event.locals, client);
	return client;
}

/** The signed-in user; without one it throws the redirect to the login page. */
export function requireUser(event: GuardEvent): SessionUser {
	if (event.locals.user !== null) return event.locals.user;
	const origin = publicOrigin(getConfig(), event.url);
	toLogin(event, origin, new CookieJar(event.cookies, origin).session());
}

/** The outcome of a promise, for loads that degrade instead of failing. */
export async function settled<T>(promise: Promise<T>): Promise<Settled<T>> {
	try {
		return { ok: true, value: await promise };
	} catch (failure) {
		return { ok: false, failure };
	}
}

/** The value of an API read, or the page outcome of its failure (see `fail`). */
export async function guarded<T>(event: GuardEvent, read: Promise<T>): Promise<T> {
	try {
		return await read;
	} catch (failure) {
		fail(event, failure);
	}
}

/**
 * Account for a failed read that a page can do without. An expired Huron token still ends the
 * session; any other API failure is logged, so an outage the page hides still leaves a trace.
 * Errors that are not API errors are rethrown unchanged.
 */
export function degrade(event: GuardEvent, failure: unknown): void {
	if (!(failure instanceof HuronApiError)) throw failure;
	if (failure.status === 401) fail(event, failure);
	logFailure(event, failure);
}

/** Whether the request URL carries a keyset cursor (`cursor` or `<list>_cursor`). */
export function hasCursor(url: URL): boolean {
	return [...url.searchParams.keys()].some(isCursorParameter);
}

/** The same path and query without cursor parameters, plus `notice=page_expired`. */
export function firstPagePath(url: URL): string {
	const next = new URL(url);
	for (const key of [...next.searchParams.keys()]) {
		if (isCursorParameter(key) || key === 'notice') next.searchParams.delete(key);
	}
	next.searchParams.append('notice', 'page_expired');
	return next.pathname + next.search;
}

/**
 * Turn a failed API read into the page outcome, with fixed copy. Errors that are not API errors
 * are rethrown unchanged. A 401 ends the session and sends the user to sign in again. Failures
 * of the API itself (5xx, unreachable, malformed answers) are logged. The 500 page shows the log
 * entry's reference; an outage (503) usually passes, so its page offers Try again instead.
 */
export function fail(event: GuardEvent, failure: unknown): never {
	if (!(failure instanceof HuronApiError)) throw failure;
	const { status, code } = failure;
	if (status === 401) endSession(event);
	if (status === 400 && code === 'INVALID_CURSOR') redirect(303, firstPagePath(event.url));
	if (status === 403) error(403, { message: FAILURE_COPY.forbidden, code });
	if (status === 404) error(404, { message: FAILURE_COPY.notFound, code });
	if (status >= 400 && status < 500) error(400, { message: FAILURE_COPY.badRequest, code });
	const id = logFailure(event, failure);
	if (status === 500 && hasCursor(event.url)) redirect(303, firstPagePath(event.url));
	if (status === 503) error(503, { message: FAILURE_COPY.unavailable, code });
	error(500, { message: FAILURE_COPY.internal, code, id });
}

/**
 * The JSON answer of an endpoint for scripts (the explorer's tree fetch) whose API read failed:
 * the status and a fixed code, never the API's `detail` or `context`. A 401 ends the session as
 * `fail` does; the script then sends the user to sign in. Failures of the API itself are logged,
 * and a 500 carries the log entry's reference. Errors that are not API errors are rethrown.
 */
export function failureResponse(event: GuardEvent, failure: unknown): Response {
	if (!(failure instanceof HuronApiError)) throw failure;
	const { status } = failure;
	if (status === 401) {
		forgetSession(event);
		return failureJson(401, { code: 'UNAUTHENTICATED' });
	}
	if (status === 403) return failureJson(403, { code: 'FORBIDDEN' });
	if (status === 404) return failureJson(404, { code: 'NOT_FOUND' });
	if (status >= 400 && status < 500) return failureJson(400, { code: 'BAD_REQUEST' });
	const id = logFailure(event, failure);
	if (status === 503) return failureJson(503, { code: 'UNAVAILABLE' });
	return failureJson(500, { code: 'INTERNAL', id });
}

/** A small JSON answer for scripts, never stored. */
export function failureJson(status: number, body: { code: string; id?: string }): Response {
	return json(body, { status, headers: { 'cache-control': 'private, no-store' } });
}

function endSession(event: GuardEvent): never {
	const origin = forgetSession(event);
	redirect(
		303,
		loginPath({
			status: 'expired',
			returnTo: safeReturnTo(event.url.pathname + event.url.search, origin)
		})
	);
}

/** Delete the session the Huron token belonged to and its cookie; returns the public origin. */
function forgetSession(event: GuardEvent): string {
	const origin = publicOrigin(getConfig(), event.url);
	const jar = new CookieJar(event.cookies, origin);
	const sessionId = jar.session();
	// Parallel loads of one request can each meet the 401, a late one even after SvelteKit
	// answered, when writing a cookie throws. Only the first still finds the cookie.
	if (sessionId !== undefined) {
		sessionStore().delete(sessionId);
		jar.deleteSession();
	}
	return origin;
}

/**
 * Log a failure of the API by its fixed vocabulary only, never the API's free text (`detail`,
 * `context`) or the query, and return its reference: the API's request id when it sent one,
 * so both services' logs share it. Loads share memoized reads, so one failure can arrive here
 * from a layout and a page; it is logged once and keeps its reference.
 */
function logFailure(event: GuardEvent, failure: HuronApiError): string {
	const logged = references.get(failure);
	if (logged !== undefined) return logged;
	const id = failure.requestId ?? randomUUID();
	references.set(failure, id);
	console.error('huron-web API call failed', {
		id,
		status: failure.status,
		code: failure.code,
		title: failure.title,
		path: event.url.pathname,
		requestId: failure.requestId ?? null
	});
	return id;
}

function toLogin(event: GuardEvent, origin: string, sessionId: string | undefined): never {
	redirect(
		303,
		loginPath({
			returnTo: safeReturnTo(event.url.pathname + event.url.search, origin),
			status: sessionId === undefined ? undefined : 'expired'
		})
	);
}
