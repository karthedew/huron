/**
 * The one-shot seed of the Docker stack (docker-compose.app.yml): loads the web's e2e demo
 * fixture (`web/e2e/support/fixture.mjs`) into the API, each call as the fixture user whose role
 * it takes, with the token exchange of `web/e2e/support/seed.mjs`.
 *
 * It works in both modes of the service configuration (huron.dev.yaml):
 * - Managed (an `organizations:` block): the service creates the declared organizations and their
 *   organization-scope role groups (`groups`) at startup, so the seed creates no organization and
 *   no organization-scope grant. The
 *   fixture's organizations the configuration does not declare are skipped with their catalogs
 *   (`POST /organizations` answers 409 ORGANIZATIONS_MANAGED).
 * - Unmanaged: it creates the fixture's missing organizations with their org_admin grants and
 *   their organization-wide catalog-role grants, which every catalog of the organization inherits.
 * Then, for every organization that exists, it creates each fixture catalog that does not exist
 * yet, with its grants, namespaces and collections, and publishes and assigns the schemas of the
 * catalogs it created. A catalog that exists is left alone, so every start of the stack may run
 * this again, and declaring an organization later seeds its catalogs on the next start.
 *
 * seed.mjs asks its issuer for ID tokens at `POST /test/id-token {"username": …}`. The shim below
 * answers with an ID token from Keycloak's password grant on the huron-cli client, for the
 * fixture's creators only: the users fixture.mjs names in createdBy, grantedBy, publishedBy and
 * assignedBy, each a user of scripts/keycloak/company-realm.json with the password "password".
 * It listens on 127.0.0.1 on a port the system picks, inside the stack's network namespace,
 * where no port of it is published, and closes when the seed is done.
 *
 * Settings, all required: HURON_SEED_API_URL (the API origin), HURON_SEED_ISSUER (Keycloak's
 * realm), HURON_SEED_CLIENT_ID (a client with the password grant) and HURON_SEED_FIXTURE_DIR
 * (the directory holding seed.mjs and fixture.mjs).
 *
 * A commit publishes sealed uploads. The seed reads `uploads_url` from the API's `/healthz` and
 * sends the bytes of each file with tus through the upload proxy and tusd: a creation, then
 * `PATCH` requests of at most 64 MiB (none for an empty file), each with the token of the fixture
 * user. Then it commits the files (`publishCommits` of seed.mjs). When the API takes no uploads
 * (`uploads_url` is null), the collections stay without files, and the seed says so.
 */
import { randomUUID } from 'node:crypto';
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
/** The most bytes of one tus `PATCH`, as in the CLI. */
const CHUNK_SIZE = 64 * 1024 * 1024;

/** Seed, then exit: the shim's server would keep the process alive. */
async function main() {
	try {
		const fixture = await import(pathToFileURL(join(FIXTURE_DIR, 'fixture.mjs')).href);
		const creators = creatorsOf(fixture);
		await waitFor(`${API_URL}/readyz`, 'the API');
		const discovery = await (
			await waitFor(`${ISSUER}/.well-known/openid-configuration`, 'Keycloak')
		).json();
		const shim = await startShim(String(discovery.token_endpoint), creators);
		console.log(
			`seed: ID token shim on ${shim.url} (inside the stack only) for ${[...creators].sort().join(', ')}`
		);
		try {
			const seeding = await import(pathToFileURL(join(FIXTURE_DIR, 'seed.mjs')).href);
			const api = new SeedApi(API_URL, (username) =>
				seeding.huronToken({ apiUrl: API_URL, issuer: shim.url }, username)
			);
			const health = await (await fetch(`${API_URL}/healthz`)).json();
			const uploadsUrl = health.uploads_url ?? null;
			if (uploadsUrl === null) {
				console.log('seed: the API takes no uploads, so the collections get no files');
			}
			const publish = uploadsUrl === null ? null : publisher(api, seeding, uploadsUrl);
			const created = await seedFixture(api, fixture, publish);
			console.log(
				created.length > 0
					? `seed: created the catalogs ${created.join(', ')}`
					: 'seed: every catalog of the demo fixture is already there; nothing changed'
			);
		} finally {
			await shim.close();
		}
	} catch (failure) {
		console.error(`seed: ${failure instanceof Error ? failure.message : String(failure)}`);
		process.exitCode = 1;
	}
	process.exit();
}

/**
 * Seed what is missing and return the names of the catalogs created.
 * @param {SeedApi} api
 * @param {Record<string, any>} fixture The exports of fixture.mjs.
 * @param {Publish | null} publish Uploads and commits the files of a collection; `null` when
 *   the API takes no uploads.
 * @returns {Promise<string[]>}
 */
async function seedFixture(api, fixture, publish) {
	const { ORGANIZATIONS, CATALOGS, NAMESPACES, COLLECTIONS, SCHEMAS } = fixture;
	const organizations = new Set();
	for (const organization of ORGANIZATIONS) {
		if (await ensureOrganization(api, organization)) organizations.add(organization.name);
	}
	const created = [];
	for (const catalog of CATALOGS) {
		if (!organizations.has(catalog.organization)) continue;
		if (await api.exists(catalog.createdBy, ['catalogs', catalog.name])) continue;
		await api.call(catalog.createdBy, 'POST', ['organizations', catalog.organization, 'catalogs'], {
			name: catalog.name,
			display_name: catalog.displayName,
			description: catalog.description
		});
		for (const grant of catalog.grants) {
			await api.call(grant.grantedBy, 'PUT', ['catalogs', catalog.name, 'grants', grant.role], {
				ldap_groups: grant.groups
			});
		}
		created.push(catalog.name);
	}
	const fresh = new Set(created);
	for (const namespace of NAMESPACES.filter((entry) => fresh.has(entry.catalog))) {
		const segments = namespace.path.split('.');
		await api.call(namespace.createdBy, 'POST', ['catalogs', namespace.catalog, 'namespaces'], {
			parent: segments.slice(0, -1).join('.'),
			name: segments[segments.length - 1],
			collections_allowed: namespace.collectionsAllowed
		});
	}
	for (const collection of COLLECTIONS.filter((entry) => fresh.has(entry.catalog))) {
		await createCollection(api, collection, publish);
	}
	for (const schema of SCHEMAS) {
		const catalogs = schema.assignedTo.filter((/** @type {string} */ name) => fresh.has(name));
		if (catalogs.length > 0) await publishAndAssign(api, schema, catalogs);
	}
	return created;
}

/**
 * Whether the organization exists after this call. One that exists is left alone (in managed
 * mode the service owns its organization-scope grants). A missing one is created with its
 * org_admin grant and its organization-wide catalog-role grants, unless the service answers that
 * organizations are managed: then it is not declared.
 * @param {SeedApi} api
 * @param {Record<string, any>} organization A fixture organization.
 * @returns {Promise<boolean>}
 */
async function ensureOrganization(api, organization) {
	const actor = organization.createdBy;
	if (await api.exists(actor, ['organizations', organization.name])) return true;
	const response = await api.send(actor, 'POST', ['organizations'], {
		name: organization.name,
		display_name: organization.displayName,
		description: organization.description
	});
	if (response.status === 409) {
		const problem = await response.json().catch(() => ({}));
		if (problem.code === 'ORGANIZATIONS_MANAGED') {
			console.log(
				`seed: ${organization.name} is not declared in the service configuration; its catalogs are skipped`
			);
			return false;
		}
		throw new Error(`POST /api/v1/organizations answered 409 ${problem.code ?? ''}`);
	}
	await api.check(response, 'POST', ['organizations'], actor);
	if (organization.orgAdmins.length > 0) {
		await api.call(actor, 'PUT', ['organizations', organization.name, 'grants', 'org_admin'], {
			ldap_groups: organization.orgAdmins
		});
	}
	for (const grant of organization.grants) {
		await api.call(
			grant.grantedBy,
			'PUT',
			['organizations', organization.name, 'grants', grant.role],
			{ ldap_groups: grant.groups }
		);
	}
	return true;
}

/**
 * A draft with its metadata and schema override, activated unless it stays a draft, then its
 * commits in order when the API takes uploads.
 * @param {SeedApi} api
 * @param {Record<string, any>} collection A fixture collection.
 * @param {Publish | null} publish
 */
async function createCollection(api, collection, publish) {
	const actor = collection.createdBy;
	let draft = await api.call(
		actor,
		'POST',
		['catalogs', collection.catalog, 'namespaces', collection.namespace, 'collections'],
		{ name: collection.name, metadata: collection.metadata }
	);
	if (collection.schemaOverride !== undefined) {
		draft = await api.call(
			actor,
			'PATCH',
			['collections', draft.id],
			{ schema_override: collection.schemaOverride },
			{ 'if-match': `"${draft.version}"` }
		);
	}
	if (collection.state === 'draft') return;
	const active = await api.call(actor, 'POST', ['collections', draft.id, 'activate'], undefined, {
		'if-match': `"${draft.version}"`
	});
	if (publish !== null) await publish(collection, draft.id, active.version);
}

/**
 * Uploads and commits the files of a fixture collection, given its ID and its version after the
 * activation.
 * @callback Publish
 * @param {Record<string, any>} collection
 * @param {string} id
 * @param {number} version
 * @returns {Promise<void>}
 */

/**
 * The `Publish` function that sends each file with tus to `uploadsUrl` (`tusUpload`), then
 * commits the files with `publishCommits` of seed.mjs.
 * @param {SeedApi} api
 * @param {Record<string, any>} seeding The exports of seed.mjs.
 * @param {string} uploadsUrl The `uploads_url` of the API.
 * @returns {Publish}
 */
function publisher(api, seeding, uploadsUrl) {
	const call = (/** @type {any[]} */ ...args) => api.call(...args);
	const upload = tusUpload(api, uploadsUrl, (/** @type {any[]} */ ...args) =>
		seeding.waitForSeal(call, ...args)
	);
	return (collection, id, version) => seeding.publishCommits(call, upload, collection, id, version);
}

/**
 * The upload function of seed.mjs over tus. For each file it sends the creation `POST` to
 * `uploadsUrl`, then the bytes in `PATCH` requests of at most `CHUNK_SIZE` bytes, each with the
 * user's token. An empty file has no `PATCH`: tusd finishes it in the creation. The address of
 * each `PATCH` is `uploadsUrl` and the upload ID, never the host of `Location`. Then it waits for
 * the seal with `wait`.
 * @param {SeedApi} api
 * @param {string} uploadsUrl
 * @param {(actor: string, attemptId: string, state: unknown, what: string) => Promise<void>} wait
 * @returns {(actor: string, collectionId: string, relPath: string, content: Buffer) => Promise<string>}
 */
function tusUpload(api, uploadsUrl, wait) {
	return async (actor, collectionId, relPath, content) => {
		const what = `${collectionId}/${relPath}`;
		const attemptId = randomUUID();
		const metadata = {
			attempt_id: attemptId,
			collection: collectionId,
			rel_path: relPath
		};
		const tus = {
			'tus-resumable': '1.0.0',
			authorization: `Bearer ${await api.token(actor)}`
		};
		let answer = await fetch(uploadsUrl, {
			method: 'POST',
			headers: {
				...tus,
				'upload-length': String(content.length),
				'upload-metadata': Object.entries(metadata)
					.map(([key, value]) => `${key} ${Buffer.from(value).toString('base64')}`)
					.join(',')
			},
			signal: AbortSignal.timeout(120_000)
		});
		await tusCheck(answer, 201, `the creation of the upload of ${what}`);
		const uploadId = new URL(String(answer.headers.get('location')), uploadsUrl).pathname
			.split('/')
			.pop();
		const address = `${uploadsUrl.replace(/\/$/, '')}/${uploadId}`;
		for (let offset = 0; offset < content.length; offset += CHUNK_SIZE) {
			answer = await fetch(address, {
				method: 'PATCH',
				headers: {
					...tus,
					'upload-offset': String(offset),
					'content-type': 'application/offset+octet-stream'
				},
				body: content.subarray(offset, offset + CHUNK_SIZE),
				signal: AbortSignal.timeout(120_000)
			});
			await tusCheck(answer, 204, `a PATCH of the upload of ${what}`);
		}
		await wait(actor, attemptId, answer.headers.get('huron-upload-state'), what);
		return String(uploadId);
	};
}

/**
 * Throw unless a tus request answered `status`.
 * @param {Response} answer
 * @param {number} status
 * @param {string} what
 */
async function tusCheck(answer, status, what) {
	if (answer.status === status) return;
	const body = (await answer.text()).slice(0, 600);
	throw new Error(`${what} answered ${answer.status}: ${body}`);
}

/**
 * Assign an organization schema to catalogs, publishing it first on top of the latest version of
 * the platform schema it extends unless the organization already has it.
 * @param {SeedApi} api
 * @param {Record<string, any>} schema A fixture schema.
 * @param {string[]} catalogs The catalogs this run created that use it.
 */
async function publishAndAssign(api, schema, catalogs) {
	const query = { limit: '500' };
	const own = await api.call(
		schema.publishedBy,
		'GET',
		['organizations', schema.organization, 'schemas'],
		undefined,
		{},
		query
	);
	let entry = newest(own.items, schema.name);
	if (entry === undefined) {
		const platform = await api.call(
			schema.publishedBy,
			'GET',
			['platform', 'schemas'],
			undefined,
			{},
			query
		);
		const parent = newest(platform.items, schema.extends);
		if (parent === undefined) throw new Error(`the API has no platform schema ${schema.extends}`);
		entry = await api.call(
			schema.publishedBy,
			'POST',
			['organizations', schema.organization, 'schemas'],
			{ name: schema.name, extends_id: parent.id, document: schema.document }
		);
	}
	for (const catalog of catalogs) {
		await api.call(schema.assignedBy, 'PUT', ['catalogs', catalog, 'schema'], {
			schema_id: entry.id
		});
	}
}

/**
 * The newest version of the named schema in a registry listing.
 * @param {Array<{ name: string, version: number, id: string }>} items
 * @param {string} name
 */
function newest(items, name) {
	return items.filter((item) => item.name === name).sort((a, b) => b.version - a.version)[0];
}

/** Calls the API as fixture users, exchanging an ID token once per user. */
class SeedApi {
	/** @type {string} */
	#apiUrl;
	/** @type {(username: string) => Promise<string>} */
	#exchange;
	/** @type {Map<string, Promise<string>>} */
	#tokens = new Map();

	/**
	 * @param {string} apiUrl
	 * @param {(username: string) => Promise<string>} exchange A Huron token for a user.
	 */
	constructor(apiUrl, exchange) {
		this.#apiUrl = apiUrl;
		this.#exchange = exchange;
	}

	/**
	 * Whether a GET answers 200 (404: no).
	 * @param {string} username
	 * @param {readonly string[]} segments
	 */
	async exists(username, segments) {
		const response = await this.send(username, 'GET', segments);
		if (response.status === 404) return false;
		await this.check(response, 'GET', segments, username);
		return true;
	}

	/**
	 * The parsed answer of a call that must succeed.
	 * @param {string} username
	 * @param {string} method
	 * @param {readonly string[]} segments Path segments below `/api/v1`, encoded here.
	 * @param {unknown} [body]
	 * @param {Record<string, string>} [headers]
	 * @param {Record<string, string>} [query]
	 * @returns {Promise<any>}
	 */
	async call(username, method, segments, body, headers = {}, query = {}) {
		const response = await this.send(username, method, segments, body, headers, query);
		await this.check(response, method, segments, username);
		const answer = await response.text();
		return answer === '' ? null : JSON.parse(answer);
	}

	/**
	 * Throw unless the response succeeded.
	 * @param {Response} response
	 * @param {string} method
	 * @param {readonly string[]} segments
	 * @param {string} username
	 */
	async check(response, method, segments, username) {
		if (response.ok) return;
		const body = (await response.text()).slice(0, 600);
		const call = `${method} /api/v1/${segments.join('/')} as ${username}`;
		throw new Error(`${call} answered ${response.status}: ${body}`);
	}

	/**
	 * @param {string} username
	 * @param {string} method
	 * @param {readonly string[]} segments
	 * @param {unknown} [body]
	 * @param {Record<string, string>} [headers]
	 * @param {Record<string, string>} [query]
	 */
	async send(username, method, segments, body, headers = {}, query = {}) {
		const url = new URL(`${this.#apiUrl}/api/v1/${segments.map(encodeURIComponent).join('/')}`);
		for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value);
		return fetch(url, {
			method,
			headers: {
				accept: 'application/json',
				authorization: `Bearer ${await this.#token(username)}`,
				...(body === undefined ? {} : { 'content-type': 'application/json' }),
				...headers
			},
			body: body === undefined ? undefined : JSON.stringify(body),
			signal: AbortSignal.timeout(30_000)
		});
	}

	/**
	 * The Huron token of a user, exchanged once.
	 * @param {string} username
	 */
	token(username) {
		return this.#token(username);
	}

	/** @param {string} username */
	#token(username) {
		let token = this.#tokens.get(username);
		if (token === undefined) {
			token = this.#exchange(username);
			this.#tokens.set(username, token);
		}
		return token;
	}
}

/**
 * The users the seed calls the API as: who creates, grants, publishes and assigns each record.
 * @param {Record<string, any>} fixture The exports of fixture.mjs.
 * @returns {Set<string>}
 */
function creatorsOf({ ORGANIZATIONS, CATALOGS, NAMESPACES, COLLECTIONS, SCHEMAS }) {
	return new Set([
		...ORGANIZATIONS.flatMap((organization) => [
			organization.createdBy,
			...organization.grants.map((grant) => grant.grantedBy)
		]),
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
		return {
			status: 403,
			body: { error: 'only the fixture creators get ID tokens' }
		};
	}
	return {
		status: 200,
		body: { id_token: await idToken(tokenEndpoint, username) }
	};
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
		headers: {
			accept: 'application/json',
			'content-type': 'application/x-www-form-urlencoded'
		},
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

// Last, once the class above is initialized.
await main();
