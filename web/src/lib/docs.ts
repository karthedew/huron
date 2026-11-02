/**
 * Where the web serves the documentation, the static Starlight build of `web/docs-site`: public,
 * outside the signed-in application (`src/lib/server/docs.ts`). Links to it reload the page,
 * as SvelteKit has no route there.
 */
export const DOCS_PATH = '/docs/';
