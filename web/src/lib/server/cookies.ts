import type { Cookies } from '@sveltejs/kit';
import { ORGANIZATION_COOKIE } from '../organization-cookie';
import { match as isSegment } from '../../params/segment';
import { getConfig, publicOrigin } from './config';

export { ORGANIZATION_COOKIE };
export const SESSION_COOKIE = 'huron_session';
export const TRANSACTION_COOKIE_PREFIX = 'huron_oidc_';
export const TRANSACTION_MAX_AGE_SECONDS = 600;

export type CookieOptions = Parameters<Cookies['set']>[2];

export interface TransactionCookie {
	/** The cookie name without the `__Host-` prefix. */
	base: string;
	value: string;
}

/** Whether cookies for `origin` are `Secure` (and therefore `__Host-` prefixed). */
export function isSecureOrigin(origin: string): boolean {
	return origin.startsWith('https:');
}

/** The cookie name for `origin`: `__Host-` prefixed on https. */
export function cookieName(base: string, origin: string): string {
	return isSecureOrigin(origin) ? `__Host-${base}` : base;
}

/**
 * Options for every set and delete. `secure` is always explicit: SvelteKit's default would mark
 * cookies `Secure` on `http://127.0.0.1`, where browsers then drop them.
 */
export function cookieOptions(
	origin: string,
	{ httpOnly = true, maxAge }: { httpOnly?: boolean; maxAge?: number } = {}
): CookieOptions {
	const options: CookieOptions = {
		path: '/',
		httpOnly,
		sameSite: 'lax',
		secure: isSecureOrigin(origin)
	};
	if (maxAge !== undefined) options.maxAge = maxAge;
	return options;
}

/** The base name of the transaction cookie for an OIDC `state`. */
export function transactionCookieBase(state: string): string {
	return `${TRANSACTION_COOKIE_PREFIX}${state.slice(0, 8)}`;
}

/** The cookie jar of a request, for the public origin. */
export function requestCookies(event: { cookies: Cookies; url: URL }): CookieJar {
	return new CookieJar(event.cookies, publicOrigin(getConfig(), event.url));
}

/** The web's cookies for one request, named and configured for the public origin. */
export class CookieJar {
	readonly #cookies: Cookies;
	readonly #origin: string;

	constructor(cookies: Cookies, origin: string) {
		this.#cookies = cookies;
		this.#origin = origin;
	}

	get(base: string): string | undefined {
		return this.#cookies.get(cookieName(base, this.#origin));
	}

	set(base: string, value: string, maxAgeSeconds: number, httpOnly = true): void {
		this.#cookies.set(
			cookieName(base, this.#origin),
			value,
			cookieOptions(this.#origin, { httpOnly, maxAge: maxAgeSeconds })
		);
	}

	delete(base: string, httpOnly = true): void {
		this.#cookies.delete(cookieName(base, this.#origin), cookieOptions(this.#origin, { httpOnly }));
	}

	session(): string | undefined {
		return this.get(SESSION_COOKIE);
	}

	setSession(id: string, maxAgeSeconds: number): void {
		this.set(SESSION_COOKIE, id, maxAgeSeconds);
	}

	deleteSession(): void {
		this.delete(SESSION_COOKIE);
	}

	/**
	 * The `set-cookie` value that deletes the session cookie, for an answer `handle` returns
	 * without `resolve()`: SvelteKit adds this request's cookie writes only to answers from
	 * `resolve()` and to thrown redirects.
	 */
	sessionDeletionHeader(): string {
		return this.#cookies.serialize(
			cookieName(SESSION_COOKIE, this.#origin),
			'',
			cookieOptions(this.#origin, { maxAge: 0 })
		);
	}

	/** Every sign-in transaction cookie the browser sent or this request set. */
	transactions(): TransactionCookie[] {
		const prefix = cookieName(TRANSACTION_COOKIE_PREFIX, this.#origin);
		const hostPrefixLength = prefix.length - TRANSACTION_COOKIE_PREFIX.length;
		return this.#cookies
			.getAll()
			.filter(({ name }) => name.startsWith(prefix) && name.length > prefix.length)
			.map(({ name, value }) => ({ base: name.slice(hostPrefixLength), value }));
	}

	setTransaction(state: string, sealed: string): void {
		this.set(transactionCookieBase(state), sealed, TRANSACTION_MAX_AGE_SECONDS);
	}

	/** The remembered organization when it is a well-formed name; visibility is checked by callers. */
	rememberedOrganization(): string | null {
		const value = this.get(ORGANIZATION_COOKIE);
		return value !== undefined && isSegment(value) ? value : null;
	}
}
