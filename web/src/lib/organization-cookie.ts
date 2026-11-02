/**
 * The cookie that remembers the last organization. The browser writes it after a navigation
 * (`(app)/+layout.svelte`); the server only reads it, through `$lib/server/cookies`.
 */
export const ORGANIZATION_COOKIE = 'huron_org';

/** One year, in seconds. */
export const ORGANIZATION_COOKIE_MAX_AGE = 31_536_000;

/**
 * The `document.cookie` assignment that remembers `organization`, with the attributes the
 * server gives its own cookies: `Path=/`, `SameSite=Lax`, and on https `Secure` and the
 * `__Host-` prefix. It is not HttpOnly, or the browser could not write it.
 */
export function organizationCookie(organization: string, secure: boolean): string {
	const name = secure ? `__Host-${ORGANIZATION_COOKIE}` : ORGANIZATION_COOKIE;
	const attributes = ['Path=/', 'SameSite=Lax', `Max-Age=${ORGANIZATION_COOKIE_MAX_AGE}`];
	if (secure) attributes.push('Secure');
	return [`${name}=${encodeURIComponent(organization)}`, ...attributes].join('; ');
}
