/**
 * The one-shot seed of the Docker stack (docker-compose.app.yml): loads the web's e2e demo
 * fixture into the API by running `web/e2e/support/seed.mjs` unchanged.
 *
 * seed.mjs asks its issuer for ID tokens at `POST /test/id-token {"username": …}`. The shim below
 * answers with an ID token from Keycloak's password grant on the huron-cli client, for the
 * fixture's creators only: the users fixture.mjs names in createdBy, grantedBy, publishedBy and
 * assignedBy, each a user of scripts/keycloak/company-realm.json with the password "password".
 * It listens on 127.0.0.1 on a port the system picks, inside the stack's network namespace,
 * where no port of it is published, and closes when the seed is done.
 *
 * seed.mjs creates nothing when the fixture's first organization exists, so every start of the
 * stack may run this again.
 *
 * Settings, all required: HURON_SEED_API_URL (the API origin), HURON_SEED_ISSUER (Keycloak's
 * realm), HURON_SEED_CLIENT_ID (a client with the password grant) and HURON_SEED_FIXTURE_DIR
 * (the directory holding seed.mjs and fixture.mjs).
 */
import { createServer } from 'node:http';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const API_URL = setting('HURON_SEED_API_URL');
const ISSUER = setting('HURON_SEED_ISSUER');
const CLIENT_ID = setting('HURON_SEED_CLIENT_ID');
const FIXTURE_DIR = setting('HURON_SEED_FIXTURE_DIR');

/** The development password of the fixture's creators in the realm. */
const PASSWORD = 'password';
const WAIT_SECONDS = 180;

try {
	const creators = creatorsOf(await import(pathToFileURL(join(FIXTURE_DIR, 'fixture.mjs')).href));
	await waitFor(`${API_URL}/readyz`, 'the API');
	const discovery = await (
		await waitFor(`${ISSUER}/.well-known/openid-configuration`, 'Keycloak')
	).json();
	const shim = await startShim(String(discovery.token_endpoint), creators);
	console.log(
		`seed: ID token shim on ${shim.url} (inside the stack only) for ${[...creators].sort().join(', ')}`
	);
	try {
		const { seed } = await import(pathToFileURL(join(FIXTURE_DIR, 'seed.mjs')).href);
		const { created } = await seed({ apiUrl: API_URL, issuer: shim.url });
		console.log(
			created
				? 'seed: the demo fixture was created'
				: 'seed: the demo fixture is already there; nothing changed'
		);
	} finally {
		await shim.close();
	}
} catch (failure) {
	console.error(`seed: ${failure instanceof Error ? failure.message : String(failure)}`);
	process.exitCode = 1;
}
process.exit();

/**
 * The users seed.mjs calls the API as: who creates, grants, publishes and assigns each record.
 * @param {Record<string, any>} fixture The exports of fixture.mjs.
 * @returns {Set<string>}
 */
function creatorsOf({ ORGANIZATIONS, CATALOGS, NAMESPACES, COLLECTIONS, SCHEMAS }) {
	return new Set([
		...ORGANIZATIONS.map((organization) => organization.createdBy),
		...CATALOGS.flatMap((catalog) => [
			catalog.createdBy,
			...catalog.grants.map((grant) => grant.grantedBy)
		]),
		...NAMESPACES.map((namespace) => namespace.createdBy),
		...COLLECTIONS.map((collection) => collection.createdBy),
		...SCHEMAS.flatMap((schema) => [schema.publishedBy, schema.assignedBy])
	]);
}

/**
 * Serve `POST /test/id-token` on 127.0.0.1 until closed.
 * @param {string} tokenEndpoint Keycloak's token endpoint.
 * @param {Set<string>} creators The users who get ID tokens.
 * @returns {Promise<{ url: string, close: () => Promise<void> }>}
 */
function startShim(tokenEndpoint, creators) {
	const server = createServer((request, response) => {
		answer(request, tokenEndpoint, creators).then(
			({ status, body }) => {
				response.writeHead(status, { 'content-type': 'application/json' });
				response.end(JSON.stringify(body));
			},
			(failure) => {
				const reason = String(failure?.message ?? failure);
				console.error(`seed: ${reason}`);
				response.writeHead(502, { 'content-type': 'application/json' });
				response.end(JSON.stringify({ error: reason }));
			}
		);
	});
	return new Promise((resolve, reject) => {
		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			const port = typeof address === 'object' && address !== null ? address.port : 0;
			resolve({
				url: `http://127.0.0.1:${port}`,
				close: () =>
					new Promise((done) => {
						server.close(() => done());
						server.closeAllConnections();
					})
			});
		});
	});
}

/**
 * The shim's answer to one request.
 * @param {import('node:http').IncomingMessage} request
 * @param {string} tokenEndpoint
 * @param {Set<string>} creators
 * @returns {Promise<{ status: number, body: Record<string, string> }>}
 */
async function answer(request, tokenEndpoint, creators) {
	if (request.method !== 'POST' || request.url !== '/test/id-token') {
		return { status: 404, body: { error: 'only POST /test/id-token' } };
	}
	let username;
	try {
		username = JSON.parse(await read(request)).username;
	} catch {
		return { status: 400, body: { error: 'the body must be JSON' } };
	}
	if (typeof username !== 'string' || !creators.has(username)) {
		console.error(
			`seed: no ID token for ${JSON.stringify(username)}, not a creator in fixture.mjs`
		);
		return { status: 403, body: { error: 'only the fixture creators get ID tokens' } };
	}
	return { status: 200, body: { id_token: await idToken(tokenEndpoint, username) } };
}

/**
 * An ID token for a creator from Keycloak's password grant.
 * @param {string} tokenEndpoint
 * @param {string} username
 * @returns {Promise<string>}
 */
async function idToken(tokenEndpoint, username) {
	const response = await fetch(tokenEndpoint, {
		method: 'POST',
		headers: { accept: 'application/json', 'content-type': 'application/x-www-form-urlencoded' },
		body: new URLSearchParams({
			grant_type: 'password',
			client_id: CLIENT_ID,
			username,
			password: PASSWORD,
			scope: 'openid profile'
		}),
		signal: AbortSignal.timeout(10_000)
	});
	const tokens = await response.json().catch(() => ({}));
	if (!response.ok || typeof tokens.id_token !== 'string') {
		const reason = `${response.status} ${tokens.error ?? ''}`.trim();
		throw new Error(`Keycloak issued no ID token for ${username}: ${reason}`);
	}
	return tokens.id_token;
}

/**
 * The first successful answer of `url`, retried each second for WAIT_SECONDS.
 * @param {string} url
 * @param {string} what
 * @returns {Promise<Response>}
 */
async function waitFor(url, what) {
	const deadline = Date.now() + WAIT_SECONDS * 1000;
	for (;;) {
		try {
			const response = await fetch(url, { signal: AbortSignal.timeout(5_000) });
			if (response.ok) return response;
		} catch {
			// Not answering yet.
		}
		if (Date.now() > deadline) {
			throw new Error(`${what} did not answer ${url} in ${WAIT_SECONDS} s`);
		}
		await new Promise((resolve) => setTimeout(resolve, 1_000));
	}
}

/** @param {import('node:http').IncomingMessage} request */
async function read(request) {
	const chunks = [];
	for await (const chunk of request) chunks.push(chunk);
	return Buffer.concat(chunks).toString('utf8');
}

/** @param {string} name */
function setting(name) {
	const value = process.env[name];
	if (!value) throw new Error(`seed: ${name} is required`);
	return value.replace(/\/+$/, '');
}
