/**
 * Route segments at the URL root that are NOT organization slugs.
 *
 * design/frontend.html §1 requires shareable deep links of the form
 * `/{org}/{project}/{dataset}/{release}`, which puts organization slugs at the root of
 * the URL space, where they collide with the app's own static routes. SvelteKit resolves
 * static routes ahead of dynamic ones, so an organization slugged `admin` would be
 * permanently unreachable in the UI.
 *
 * This list is the UI's half of the contract; ``RESERVED_ROOT_SLUGS`` in
 * ``pkg/catalog/paths.py`` is the other half, and refuses these at
 * organization-creation time on the API side. `auth` remains reserved ahead
 * of the callback routes that will claim it; the API already refuses it as an
 * organization slug.
 */
export const RESERVED_ROOT_SLUGS = [
	'account',
	'admin',
	'auth',
	'browse',
	'ingestion',
	'login',
	'logout',
	'product',
	'queue',
	'settings',
	'signup',
	'snapshot'
] as const;

export function isReservedRootSlug(slug: string): boolean {
	return (RESERVED_ROOT_SLUGS as readonly string[]).includes(slug);
}
