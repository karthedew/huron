/**
 * Seeds the fixture of `fixture.mjs` through the real API, each call as the user whose role it
 * takes: alice (platform admin) creates the organizations, bob (org admin of helio) its
 * organization-wide grants, its catalogs and its schema, carol (catalog admin) namespaces, member grants and the schema
 * assignment, dave (contributor) the helio collections and their commits. Tokens come from the
 * fake IdP's `POST /test/id-token` and the API's exchange.
 *
 * A commit publishes uploads, so the seed does tusd's part of each upload: it sends the
 * `pre-create` hook, writes the bytes and the `.info` file into the lake's `.tus-uploads`, and
 * sends the `pre-finish` hook, which seals the upload. The API must hold the lake at `lakePath`.
 */
import { randomUUID } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import {
	CATALOGS,
	COLLECTIONS,
	NAMESPACES,
	ORGANIZATIONS,
	SCHEMAS,
	collectionIdentifier,
	fileContent,
	fileSha256
} from './fixture.mjs';

/** @typedef {import('./fixture.mjs').Username} Username */
/** @typedef {import('./fixture.mjs').FixtureCollection} FixtureCollection */
/** @typedef {import('./fixture.mjs').FixtureSchema} FixtureSchema */

/**
 * @typedef {object} SeedOptions
 * @property {string} apiUrl The API origin; `/api/v1` is appended.
 * @property {string} issuer The fake IdP.
 * @property {string} [lakePath] The API's lake, into whose `.tus-uploads` the seed writes the
 *   bytes of each upload. Only `seed` needs it.
 */

/**
 * Calls the API as a fixture user, as `SeedClient.call` does.
 * @callback ApiCall
 * @param {Username} username
 * @param {'GET' | 'POST' | 'PUT' | 'PATCH'} method
 * @param {readonly string[]} segments
 * @param {unknown} [body]
 * @returns {Promise<any>}
 */

/**
 * Create the fixture. When it is already there (the first organization exists) nothing is
 * touched, so each item is created once per API process even if the seed runs again.
 * @param {SeedOptions} options
 * @returns {Promise<{ created: boolean }>}
 */
export async function seed({ apiUrl, issuer, lakePath }) {
	if (lakePath === undefined) throw new Error('the seed needs the lake path of the API');
	const api = new SeedClient(apiUrl, issuer);
	const first = ORGANIZATIONS[0];
	if (await api.exists(first.createdBy, ['organizations', first.name])) return { created: false };

	for (const organization of ORGANIZATIONS) {
		await api.call(organization.createdBy, 'POST', ['organizations'], {
			name: organization.name,
			display_name: organization.displayName,
			description: organization.description
		});
		if (organization.orgAdmins.length > 0) {
			await api.call(
				organization.createdBy,
				'PUT',
				['organizations', organization.name, 'grants', 'org_admin'],
				{ ldap_groups: organization.orgAdmins }
			);
		}
		for (const grant of organization.grants) {
			await api.call(
				grant.grantedBy,
				'PUT',
				['organizations', organization.name, 'grants', grant.role],
				{ ldap_groups: grant.groups }
			);
		}
	}
	for (const catalog of CATALOGS) {
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
	}
	for (const namespace of NAMESPACES) {
		const segments = namespace.path.split('.');
		await api.call(namespace.createdBy, 'POST', ['catalogs', namespace.catalog, 'namespaces'], {
			parent: segments.slice(0, -1).join('.'),
			name: segments[segments.length - 1],
			collections_allowed: namespace.collectionsAllowed
		});
	}
	for (const collection of COLLECTIONS) await createCollection(api, collection, lakePath);
	for (const schema of SCHEMAS) await publishAndAssign(api, schema);
	return { created: true };
}

/**
 * A draft with its metadata and schema override, activated unless it stays a draft, then its
 * commits in order.
 * @param {SeedClient} api
 * @param {FixtureCollection} collection
 * @param {string} lakePath
 */
async function createCollection(api, collection, lakePath) {
	const identifier = collectionIdentifier(collection);
	const actor = collection.createdBy;
	let draft = await api.call(
		actor,
		'POST',
		['catalogs', collection.catalog, 'namespaces', collection.namespace, 'collections'],
		{ name: collection.name, metadata: collection.metadata }
	);
	const id = text(draft, 'id');
	if (collection.schemaOverride !== undefined) {
		draft = await api.call(
			actor,
			'PATCH',
			['collections', id],
			{ schema_override: collection.schemaOverride },
			{ 'if-match': `"${number(draft, 'version')}"` }
		);
	}
	if (collection.state === 'draft') return;
	const active = await api.call(actor, 'POST', ['collections', id, 'activate'], undefined, {
		'if-match': `"${number(draft, 'version')}"`
	});
	const call = /** @type {ApiCall} */ ((...args) => api.call(...args));
	await publishCommits(call, lakePath, collection, id, number(active, 'version'));
}

/**
 * Upload the files of each commit of a fixture collection, then commit them, in order. Each
 * upload goes through tusd's hooks, with the bytes written into the lake's `.tus-uploads`; each
 * commit has a new request ID, and a commit that answers 202 is read until it succeeds.
 * @param {ApiCall} call
 * @param {string} lakePath
 * @param {FixtureCollection} collection
 * @param {string} id The collection's ID.
 * @param {number} version The collection's version after its activation.
 */
export async function publishCommits(call, lakePath, collection, id, version) {
	const identifier = collectionIdentifier(collection);
	const actor = collection.createdBy;
	let base = version;
	for (const commit of collection.commits) {
		const adds = [];
		for (const { relPath, size } of commit.adds) {
			const uploadId = await upload(call, lakePath, actor, id, identifier, relPath);
			adds.push({
				rel_path: relPath,
				size,
				sha256: fileSha256(identifier, relPath),
				upload_id: uploadId
			});
		}
		let result = await call(actor, 'POST', ['collections', id, 'commits'], {
			request_id: randomUUID(),
			base_version: base,
			adds,
			removes: commit.removes,
			host: commit.host,
			...(commit.message === null ? {} : { message: commit.message })
		});
		while (text(result, 'state') === 'accepted') {
			await new Promise((resolve) => setTimeout(resolve, 100));
			result = await call(actor, 'GET', ['commit-requests', text(result, 'request_id')]);
		}
		if (text(result, 'state') !== 'succeeded') {
			throw new Error(`the commit of ${identifier} is ${text(result, 'state')}`);
		}
		base = number(result, 'version');
	}
}

/**
 * One sealed upload of a fixture file, as tusd and the API make it: the upload ID.
 * @param {ApiCall} call
 * @param {string} lakePath
 * @param {Username} actor
 * @param {string} collectionId
 * @param {string} identifier
 * @param {string} relPath
 */
async function upload(call, lakePath, actor, collectionId, identifier, relPath) {
	const content = fileContent(identifier, relPath);
	const metadata = { attempt_id: randomUUID(), collection: collectionId, rel_path: relPath };
	const created = await call(actor, 'POST', ['uploads', 'hooks'], {
		Type: 'pre-create',
		Event: {
			Upload: { ID: '', Size: content.length, MetaData: metadata },
			HTTPRequest: { Method: 'POST', URI: '/files/', Header: {} }
		}
	});
	const uploadId = text(/** @type {Record<string, unknown>} */ (created).ChangeFileInfo, 'ID');
	const data = join(lakePath, '.tus-uploads', uploadId);
	await writeFile(data, content, { mode: 0o600 });
	const info = { ID: uploadId, Size: content.length, SizeIsDeferred: false, Offset: 0 };
	await writeFile(`${data}.info`, JSON.stringify(info), { mode: 0o600 });
	const finished = await call(actor, 'POST', ['uploads', 'hooks'], {
		Type: 'pre-finish',
		Event: {
			Upload: { ID: uploadId, Size: content.length },
			HTTPRequest: { Method: 'PATCH', URI: `/files/${uploadId}`, Header: {} }
		}
	});
	let state = finished?.HTTPResponse?.Header?.['Huron-Upload-State'];
	while (state === 'sealing') {
		const attempt = await call(actor, 'GET', ['upload-attempts', metadata.attempt_id]);
		state = text(attempt, 'state');
	}
	if (state !== 'ready') {
		throw new Error(
			`the upload of ${identifier}/${relPath} is not sealed: ${JSON.stringify(finished)}`
		);
	}
	return uploadId;
}

/**
 * Publish an organization schema on top of the latest version of the platform schema it
 * extends, then assign it, which re-validates the catalog's collections.
 * @param {SeedClient} api
 * @param {FixtureSchema} schema
 */
async function publishAndAssign(api, schema) {
	const platform = await api.call(
		schema.publishedBy,
		'GET',
		['platform', 'schemas'],
		undefined,
		{},
		{
			limit: '500'
		}
	);
	const parent = list(platform, 'items')
		.filter((entry) => text(entry, 'name') === schema.extends)
		.sort((a, b) => number(b, 'version') - number(a, 'version'))[0];
	if (parent === undefined) throw new Error(`the API has no platform schema ${schema.extends}`);
	const published = await api.call(
		schema.publishedBy,
		'POST',
		['organizations', schema.organization, 'schemas'],
		{ name: schema.name, extends_id: text(parent, 'id'), document: schema.document }
	);
	for (const catalog of schema.assignedTo) {
		await api.call(schema.assignedBy, 'PUT', ['catalogs', catalog, 'schema'], {
			schema_id: text(published, 'id')
		});
	}
}

/**
 * A Huron token for a fixture user: an ID token from the fake IdP, exchanged at the API.
 * @param {SeedOptions} options
 * @param {Username} username
 * @returns {Promise<string>}
 */
export async function huronToken({ apiUrl, issuer }, username) {
	const issued = await fetch(`${issuer}/test/id-token`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ username })
	});
	if (!issued.ok)
		throw new Error(`the fake IdP issued no ID token for ${username}: ${issued.status}`);
	const exchanged = await fetch(`${apiUrl}/api/v1/auth/exchange`, {
		method: 'POST',
		headers: { accept: 'application/json', 'content-type': 'application/json' },
		body: JSON.stringify({ company_token: text(await issued.json(), 'id_token') })
	});
	if (!exchanged.ok)
		throw new Error(await failure(exchanged, 'POST', ['auth', 'exchange'], username));
	return text(await exchanged.json(), 'huron_token');
}

/** Calls the API as fixture users, exchanging an ID token from the fake IdP once per user. */
class SeedClient {
	/** @type {string} */
	#apiUrl;
	/** @type {string} */
	#issuer;
	/** @type {Map<Username, Promise<string>>} */
	#tokens = new Map();

	/**
	 * @param {string} apiUrl
	 * @param {string} issuer
	 */
	constructor(apiUrl, issuer) {
		this.#apiUrl = apiUrl;
		this.#issuer = issuer;
	}

	/**
	 * Whether a GET answers 200 (404: no).
	 * @param {Username} username
	 * @param {readonly string[]} segments
	 */
	async exists(username, segments) {
		const response = await this.#send(username, 'GET', segments, undefined, {}, {});
		if (response.status === 404) return false;
		if (response.ok) return true;
		throw new Error(await failure(response, 'GET', segments, username));
	}

	/**
	 * The parsed answer of a call that must succeed.
	 * @param {Username} username
	 * @param {'GET' | 'POST' | 'PUT' | 'PATCH'} method
	 * @param {readonly string[]} segments Path segments below `/api/v1`, encoded here.
	 * @param {unknown} [body]
	 * @param {Record<string, string>} [headers]
	 * @param {Record<string, string>} [query]
	 * @returns {Promise<unknown>}
	 */
	async call(username, method, segments, body, headers = {}, query = {}) {
		const response = await this.#send(username, method, segments, body, headers, query);
		if (!response.ok) throw new Error(await failure(response, method, segments, username));
		const answer = await response.text();
		return answer === '' ? null : JSON.parse(answer);
	}

	/**
	 * @param {Username} username
	 * @param {string} method
	 * @param {readonly string[]} segments
	 * @param {unknown} body
	 * @param {Record<string, string>} headers
	 * @param {Record<string, string>} query
	 */
	async #send(username, method, segments, body, headers, query) {
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
			body: body === undefined ? undefined : JSON.stringify(body)
		});
	}

	/** @param {Username} username */
	#token(username) {
		let token = this.#tokens.get(username);
		if (token === undefined) {
			token = huronToken({ apiUrl: this.#apiUrl, issuer: this.#issuer }, username);
			this.#tokens.set(username, token);
		}
		return token;
	}
}

/**
 * @param {Response} response
 * @param {string} method
 * @param {readonly string[]} segments
 * @param {Username} username
 */
async function failure(response, method, segments, username) {
	const body = (await response.text()).slice(0, 600);
	const call = `${method} /api/v1/${segments.join('/')} as ${username}`;
	return `seed: ${call} answered ${response.status}: ${body}`;
}

/**
 * @param {unknown} value
 * @param {string} key
 * @returns {unknown}
 */
function member(value, key) {
	if (typeof value !== 'object' || value === null || !(key in value)) {
		throw new Error(`seed: the API answer has no ${key}`);
	}
	return Object.entries(value).find(([name]) => name === key)?.[1];
}

/**
 * @param {unknown} value
 * @param {string} key
 * @returns {string}
 */
function text(value, key) {
	const found = member(value, key);
	if (typeof found !== 'string') throw new Error(`seed: ${key} in the API answer is not a string`);
	return found;
}

/**
 * @param {unknown} value
 * @param {string} key
 * @returns {number}
 */
function number(value, key) {
	const found = member(value, key);
	if (typeof found !== 'number') throw new Error(`seed: ${key} in the API answer is not a number`);
	return found;
}

/**
 * @param {unknown} value
 * @param {string} key
 * @returns {unknown[]}
 */
function list(value, key) {
	const found = member(value, key);
	if (!Array.isArray(found)) throw new Error(`seed: ${key} in the API answer is not a list`);
	return found;
}
