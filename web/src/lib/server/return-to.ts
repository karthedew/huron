const MAX_LENGTH = 1024;
const CONTROL = /\p{Cc}/u;
/** Paths a sign-in must never return to: they would restart or undo it. */
const AUTH_PATHS = /^\/(?:login|logout|auth)(?:\/|$)/;

/**
 * A same-origin path to continue at after sign-in, or `/`.
 *
 * The result is `pathname + search` of the URL the value resolves to: ASCII, percent-encoded,
 * without fragment and starting with exactly one `/`, so it is safe in a `Location` header and
 * cannot leave `origin`.
 */
export function safeReturnTo(value: string | null | undefined, origin: string): string {
	if (!value || value.length > MAX_LENGTH) return '/';
	if (!value.startsWith('/') || value.startsWith('//')) return '/';
	if (value.includes('\\') || CONTROL.test(value)) return '/';
	let url: URL;
	try {
		url = new URL(value, origin);
	} catch {
		return '/';
	}
	// Dot segments can normalize to a leading `//` (`/..//evil.com`, `/%2e//evil.com`), which a
	// browser reads in a `Location` header as another host.
	if (url.origin !== origin || url.pathname.startsWith('//') || isAuthPath(url.pathname)) {
		return '/';
	}
	const result = url.pathname + url.search;
	return result.length > MAX_LENGTH ? '/' : result;
}

/** `/login` with the given query parameters in order; `undefined` values are left out. */
export function loginPath(params: Record<string, string | undefined> = {}): string {
	const query = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined) query.set(key, value);
	}
	const search = query.toString();
	return search === '' ? '/login' : `/login?${search}`;
}

/** Whether a pathname is, or decodes to, a sign-in, callback or logout path. */
function isAuthPath(pathname: string): boolean {
	let decoded: string;
	try {
		decoded = decodeURIComponent(pathname);
	} catch {
		return true;
	}
	return [pathname, decoded].some((path) => AUTH_PATHS.test(path.replace(/\/+$/, '') || '/'));
}
