/**
 * The lake of the e2e and demo APIs: an empty directory with the service's root marker, made
 * again before each start, so no upload or published file of an earlier run stays.
 *
 * Run as a program, it reads the API's own environment (`HURON_LAKE_PATH`, `HURON_ISSUER`,
 * `HURON_INSTANCE_ID`), as `apiEnvironment` in `stack.mjs` sets it.
 */
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

/** The name of the marker file, as `MARKER_FILE` in `src/huron/core/storage/layout.py`. */
export const MARKER_FILE = '.huron';

/**
 * Make `lakePath` an empty lake of the service `instanceId` at `apiUrl`.
 * @param {string} lakePath
 * @param {string} apiUrl
 * @param {string} instanceId
 */
export async function prepareLake(lakePath, apiUrl, instanceId) {
	await rm(lakePath, { recursive: true, force: true });
	await mkdir(lakePath, { recursive: true });
	// The bytes of `render_marker` in `src/huron/core/storage/marker.py`: sorted keys.
	const marker = { api_url: apiUrl, huron: 1, instance_id: instanceId };
	await writeFile(join(lakePath, MARKER_FILE), `${JSON.stringify(marker)}\n`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
	const { HURON_LAKE_PATH, HURON_ISSUER, HURON_INSTANCE_ID } = process.env;
	if (!HURON_LAKE_PATH || !HURON_ISSUER || !HURON_INSTANCE_ID) {
		throw new Error('lake.mjs needs HURON_LAKE_PATH, HURON_ISSUER and HURON_INSTANCE_ID');
	}
	await prepareLake(HURON_LAKE_PATH, HURON_ISSUER, HURON_INSTANCE_ID);
}
