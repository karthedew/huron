/**
 * Where a directory is on the share, as the CLI's `Mount` resolves it. An organization the service
 * configuration declares with a root lives at `<root>/<organization>`, and the API names that root
 * as `share_root` on every catalog, namespace and collection of it; any other organization lives
 * under the mount prefix the web is configured with (`HURON_WEB_MOUNT_PREFIX`). Either way the
 * API's relative paths (`<organization>/<catalog>/…`) go on unchanged below it.
 */
export function sharePath(shareRoot: string | null, mountPrefix: string, relative: string): string {
	return `${base(shareRoot ?? mountPrefix)}/${relative}`;
}

/** A root without its trailing slashes, so the root `/` joins as `/<relative>`. */
function base(root: string): string {
	return root.replace(/\/+$/, '');
}
