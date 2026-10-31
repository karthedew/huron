import type { ExchangeOut } from '$api/openapi';
import type {
	AuditEntry,
	Catalog,
	Collection,
	CollectionProblem,
	Commit,
	EffectiveGroups,
	FileRecord,
	JsonSchemaDocument,
	JsonValue,
	Namespace,
	Organization,
	Page,
	RoleGrant,
	SchemaEntry,
	SchemaRef,
	WhoAmI
} from '$api/types';
import {
	DecodeError,
	JsonFields,
	asArray,
	asObject,
	isJsonObject,
	parseJson,
	parseJsonExactly,
	type Decoder
} from './json';

export interface PageRequest {
	cursor?: string | null;
	limit?: number;
}

export interface CatalogQuery extends PageRequest {
	organization?: string;
}

export interface SearchQuery extends PageRequest {
	q?: string;
	/** `key=value` filters; each becomes one `label` parameter. */
	labels?: readonly string[];
	states?: readonly string[];
}

/** What a caller may add to a request. */
export interface RequestOptions {
	/**
	 * Aborts the request, on top of the client's timeout; an aborted request fails as the API
	 * being unreachable. A request with a signal is never shared with other callers (see
	 * `memoize`), whom aborting it would fail too.
	 */
	signal?: AbortSignal;
	/**
	 * Keep the digits of integers past 2^53 (`parseJsonExactly`), for an answer whose digits a
	 * page shows. Shared only with other exact reads of the same address.
	 */
	exact?: boolean;
}

export interface HuronApiErrorInit {
	status: number;
	code: string;
	title: string;
	detail?: string;
	context?: Record<string, unknown>;
	requestId?: string;
}

/**
 * A failed API call. `detail` and `context` are the API's own free text: never show or log
 * them; `requestId` finds the API's own log entry. Network failures and timeouts are
 * `503 API_UNREACHABLE`; answers that are not problem documents have the code `HTTP`.
 */
export class HuronApiError extends Error {
	readonly status: number;
	readonly code: string;
	readonly title: string;
	readonly detail: string;
	readonly context: Record<string, unknown>;
	readonly requestId?: string;

	constructor({ status, code, title, detail = '', context = {}, requestId }: HuronApiErrorInit) {
		super(`Huron API answered ${status} ${code}`);
		this.name = 'HuronApiError';
		this.status = status;
		this.code = code;
		this.title = title;
		this.detail = detail;
		this.context = context;
		if (requestId !== undefined) this.requestId = requestId;
	}
}

export interface HuronApiOptions {
	/** The API origin; `/api/v1` is appended. */
	baseUrl: string;
	token: string;
	fetch?: typeof fetch;
	timeoutMs: number;
	/** Share GET answers by URL; for clients that live for one request. */
	memoize?: boolean;
	/** The most bytes of one answer it reads; `MAX_ANSWER_BYTES` unless a test sets fewer. */
	maxAnswerBytes?: number;
}

/**
 * The most bytes the web reads of one API answer; a longer one fails as a `502` without being
 * read further. Lists carry each collection whole, metadata of up to a mebibyte and a schema
 * override the API puts no limit on, so one answer could otherwise fill the web's single
 * process, whose memory also holds every user's session. 64 MiB is well above any first page of
 * 50 collections whose metadata keeps to the API's limit.
 */
export const MAX_ANSWER_BYTES = 64 * 1024 * 1024;

/**
 * The Huron API, called with the signed-in user's Huron token.
 *
 * The token sits in a private field, so an instance can never be serialized into page data.
 * Requests use the global fetch without cookies: SvelteKit's `event.fetch` would forward the
 * browser's cookies to same-site hosts.
 */
export class HuronApi {
	readonly #baseUrl: string;
	readonly #token: string;
	readonly #fetch: typeof fetch;
	readonly #timeoutMs: number;
	readonly #maxAnswerBytes: number;
	readonly #json: Map<string, Promise<JsonValue>> | undefined;
	readonly #text: Map<string, Promise<string>> | undefined;

	constructor({
		baseUrl,
		token,
		fetch = globalThis.fetch,
		timeoutMs,
		memoize = false,
		maxAnswerBytes = MAX_ANSWER_BYTES
	}: HuronApiOptions) {
		this.#baseUrl = baseUrl;
		this.#token = token;
		this.#fetch = fetch;
		this.#timeoutMs = timeoutMs;
		this.#maxAnswerBytes = maxAnswerBytes;
		this.#json = memoize ? new Map() : undefined;
		this.#text = memoize ? new Map() : undefined;
	}

	whoami(): Promise<WhoAmI> {
		return this.#get(['auth', 'whoami'], [], whoAmI);
	}

	organizations(page: PageRequest = {}): Promise<Page<Organization>> {
		return this.#get(['organizations'], pageQuery(page), pageOf(organization));
	}

	organization(name: string): Promise<Organization> {
		return this.#get(['organizations', name], [], organization);
	}

	catalogs({ organization: owner, ...page }: CatalogQuery = {}): Promise<Page<Catalog>> {
		const query: Query = owner === undefined ? [] : [['organization', owner]];
		return this.#get(['catalogs'], [...query, ...pageQuery(page)], pageOf(catalog));
	}

	catalog(name: string): Promise<Catalog> {
		return this.#get(['catalogs', name], [], catalog);
	}

	/** The catalog's resolved schema, its integers past 2^53 with their digits (`exact`). */
	catalogSchema(name: string): Promise<JsonSchemaDocument> {
		return this.#get(['catalogs', name, 'schema'], [], schemaDocument, { exact: true });
	}

	catalogGrants(name: string): Promise<EffectiveGroups> {
		return this.#get(['catalogs', name, 'grants'], [], effectiveGroups);
	}

	catalogLog(name: string, page: PageRequest = {}): Promise<Page<AuditEntry>> {
		return this.#get(['catalogs', name, 'log'], pageQuery(page), pageOf(auditEntry));
	}

	/** Direct children of `parent` (a dotted path; empty for the catalog root). */
	namespaces(
		catalogName: string,
		parent: string,
		page: PageRequest = {}
	): Promise<Page<Namespace>> {
		const query: Query = parent === '' ? [] : [['parent', parent]];
		return this.#get(
			['catalogs', catalogName, 'namespaces'],
			[...query, ...pageQuery(page)],
			pageOf(namespace)
		);
	}

	namespace(catalogName: string, path: string): Promise<Namespace> {
		return this.#get(['catalogs', catalogName, 'namespaces', path], [], namespace);
	}

	namespaceCollections(
		catalogName: string,
		path: string,
		page: PageRequest = {}
	): Promise<Page<Collection>> {
		return this.#get(
			['catalogs', catalogName, 'namespaces', path, 'collections'],
			pageQuery(page),
			pageOf(collection)
		);
	}

	/** A collection by its identifier without the catalog (`namespace.path.name`). */
	collectionByIdentifier(
		catalogName: string,
		rest: string,
		options: RequestOptions = {}
	): Promise<Collection> {
		return this.#get(['catalogs', catalogName, 'collections', rest], [], collection, options);
	}

	collection(id: string, options: RequestOptions = {}): Promise<Collection> {
		return this.#get(['collections', id], [], collection, options);
	}

	/** The collection's resolved schema, its integers past 2^53 with their digits (`exact`). */
	collectionSchema(id: string): Promise<JsonSchemaDocument> {
		return this.#get(['collections', id, 'schema'], [], schemaDocument, { exact: true });
	}

	/** The canonical `metadata.json` text, byte for byte. */
	async collectionSidecar(id: string): Promise<string> {
		const url = this.#url(['collections', id, 'metadata.json'], []);
		return this.#memo(this.#text, url.href, () =>
			request(this.#fetch, url, this.#init('GET'), this.#timeoutMs, true).then((response) =>
				readText(response, this.#maxAnswerBytes)
			)
		);
	}

	files(id: string, page: PageRequest = {}): Promise<Page<FileRecord>> {
		return this.#get(['collections', id, 'files'], pageQuery(page), pageOf(fileRecord));
	}

	commits(id: string, page: PageRequest = {}): Promise<Page<Commit>> {
		return this.#get(['collections', id, 'commits'], pageQuery(page), pageOf(commit));
	}

	collectionLog(id: string, page: PageRequest = {}): Promise<Page<AuditEntry>> {
		return this.#get(['collections', id, 'log'], pageQuery(page), pageOf(auditEntry));
	}

	search(
		catalogName: string,
		{ q, labels = [], states = [], ...page }: SearchQuery = {},
		options: RequestOptions = {}
	): Promise<Page<Collection>> {
		const query: Query = [
			...(q === undefined || q === '' ? [] : [['q', q] as const]),
			...labels.map((label) => ['label', label] as const),
			...states.map((state) => ['state', state] as const),
			...pageQuery(page)
		];
		return this.#get(['catalogs', catalogName, 'search'], query, pageOf(collection), options);
	}

	/** A registry entry; used to name schema ids in activity rows. */
	schema(id: string): Promise<SchemaEntry> {
		return this.#get(['schemas', id], [], schemaEntry);
	}

	async #get<T>(
		segments: readonly string[],
		query: Query,
		decode: Decoder<T>,
		{ signal, exact = false }: RequestOptions = {}
	): Promise<T> {
		const url = this.#url(segments, query);
		const cache = signal === undefined ? this.#json : undefined;
		// An exact parse keeps what a plain one rounds: the two never share an answer.
		const key = exact ? `exact ${url.href}` : url.href;
		const body = await this.#memo(cache, key, () =>
			request(this.#fetch, url, this.#init('GET'), this.#timeoutMs, true, signal).then((response) =>
				readJson(response, this.#maxAnswerBytes, exact)
			)
		);
		return decodeAnswer(body, decode);
	}

	#url(segments: readonly string[], query: Query): URL {
		return apiUrl(this.#baseUrl, segments, query);
	}

	#init(method: 'GET'): RequestInit {
		return {
			method,
			headers: { accept: 'application/json', authorization: `Bearer ${this.#token}` }
		};
	}

	#memo<T>(
		cache: Map<string, Promise<T>> | undefined,
		key: string,
		load: () => Promise<T>
	): Promise<T> {
		if (cache === undefined) return load();
		const cached = cache.get(key);
		if (cached !== undefined) return cached;
		const loaded = load();
		cache.set(key, loaded);
		return loaded;
	}
}

export interface ExchangeOptions {
	baseUrl: string;
	fetch?: typeof fetch;
	timeoutMs: number;
}

/** Exchange a company ID token for a Huron token (`POST /api/v1/auth/exchange`). */
export async function exchange(
	companyToken: string,
	options: ExchangeOptions
): Promise<ExchangeOut> {
	const url = apiUrl(options.baseUrl, ['auth', 'exchange'], []);
	const init: RequestInit = {
		method: 'POST',
		headers: { accept: 'application/json', 'content-type': 'application/json' },
		body: JSON.stringify({ company_token: companyToken })
	};
	const response = await request(
		options.fetch ?? globalThis.fetch,
		url,
		init,
		options.timeoutMs,
		false
	);
	return decodeAnswer(await readJson(response, MAX_ANSWER_BYTES), exchangeOut);
}

type Query = ReadonlyArray<readonly [string, string]>;

/** Codes of the socket errors undici reports when a kept-alive connection was reset. */
const RESET_CODES = new Set(['ECONNRESET', 'EPIPE', 'UND_ERR_SOCKET']);

/**
 * Characters a segment must not hold even encoded: the API server decodes `%2F` before routing,
 * so `catalog('x/grants')` would reach another endpoint; `\` and `%` invite the same in proxies.
 */
const STRUCTURAL = /[/\\%]/;

function apiUrl(baseUrl: string, segments: readonly string[], query: Query): URL {
	const path = segments.map((segment) => encodeURIComponent(checkSegment(segment))).join('/');
	const url = new URL(`${baseUrl}/api/v1/${path}`);
	for (const [key, value] of query) url.searchParams.append(key, value);
	return url;
}

function checkSegment(segment: string): string {
	if (segment === '' || segment === '.' || segment === '..' || STRUCTURAL.test(segment)) {
		throw new HuronApiError({
			status: 400,
			code: 'INVALID_SEGMENT',
			title: 'Invalid path segment'
		});
	}
	return segment;
}

function pageQuery({ cursor, limit }: PageRequest): Query {
	const query: Array<readonly [string, string]> = [];
	if (cursor) query.push(['cursor', cursor]);
	if (limit !== undefined) query.push(['limit', String(limit)]);
	return query;
}

async function request(
	fetcher: typeof fetch,
	url: URL,
	init: RequestInit,
	timeoutMs: number,
	idempotent: boolean,
	signal?: AbortSignal
): Promise<Response> {
	const attempt = () => {
		const timeout = AbortSignal.timeout(timeoutMs);
		return fetcher(url, {
			...init,
			credentials: 'omit',
			redirect: 'error',
			signal: signal === undefined ? timeout : AbortSignal.any([timeout, signal])
		});
	};
	try {
		return await attempt();
	} catch (failure) {
		if (!idempotent || signal?.aborted || !isConnectionReset(failure)) throw unreachable();
	}
	try {
		return await attempt();
	} catch {
		throw unreachable();
	}
}

function isConnectionReset(failure: unknown): boolean {
	const cause = failure instanceof Error ? failure.cause : undefined;
	for (const candidate of [failure, cause]) {
		if (typeof candidate === 'object' && candidate !== null && 'code' in candidate) {
			if (typeof candidate.code === 'string' && RESET_CODES.has(candidate.code)) return true;
		}
	}
	return false;
}

function unreachable(): HuronApiError {
	return new HuronApiError({
		status: 503,
		code: 'API_UNREACHABLE',
		title: 'Huron API unreachable'
	});
}

async function readText(response: Response, maxBytes: number): Promise<string> {
	let text: string;
	try {
		text = await boundedText(response, maxBytes);
	} catch (failure) {
		if (failure instanceof HuronApiError) throw failure;
		throw unreachable();
	}
	if (!response.ok) throw problem(response, text);
	return text;
}

/**
 * The body as UTF-8 text, read until it holds more than `maxBytes`: then the rest is never
 * read, and the answer fails as too large.
 */
async function boundedText(response: Response, maxBytes: number): Promise<string> {
	if (Number(response.headers.get('content-length') ?? '') > maxBytes) {
		await response.body?.cancel();
		throw tooLarge();
	}
	if (response.body === null) return '';
	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let size = 0;
	let text = '';
	for (;;) {
		const { done, value } = await reader.read();
		if (done) return text + decoder.decode();
		size += value.byteLength;
		if (size > maxBytes) {
			await reader.cancel();
			throw tooLarge();
		}
		text += decoder.decode(value, { stream: true });
	}
}

async function readJson(response: Response, maxBytes: number, exact = false): Promise<JsonValue> {
	const text = await readText(response, maxBytes);
	const body = exact ? parseJsonExactly(text) : parseJson(text);
	if (body === undefined) throw malformed();
	return body;
}

function problem(response: Response, text: string): HuronApiError {
	const contentType = response.headers.get('content-type') ?? '';
	const body = parseJson(text);
	if (contentType.includes('application/problem+json') && isJsonObject(body)) {
		const { code, title, detail, context } = body;
		if (typeof code === 'string' && code !== '') {
			const details = isJsonObject(context) ? context : {};
			const requestId = details.request_id;
			return new HuronApiError({
				status: response.status,
				code,
				title: typeof title === 'string' ? title : '',
				detail: typeof detail === 'string' ? detail : '',
				context: details,
				...(typeof requestId === 'string' ? { requestId } : {})
			});
		}
	}
	return new HuronApiError({
		status: response.status,
		code: 'HTTP',
		title: response.statusText || `HTTP ${response.status}`
	});
}

function malformed(): HuronApiError {
	return new HuronApiError({ status: 502, code: 'HTTP', title: 'Malformed API answer' });
}

function tooLarge(): HuronApiError {
	return new HuronApiError({ status: 502, code: 'HTTP', title: 'API answer too large' });
}

function decodeAnswer<T>(body: JsonValue, decode: Decoder<T>): T {
	try {
		return decode(body, 'answer');
	} catch (failure) {
		if (failure instanceof DecodeError) throw malformed();
		throw failure;
	}
}

function pageOf<T>(item: Decoder<T>): Decoder<Page<T>> {
	return (value, path) => {
		const fields = new JsonFields(value, path);
		return {
			items: fields.get('items', asArray(item)),
			next_cursor: fields.nullableString('next_cursor')
		};
	};
}

const schemaDocument: Decoder<JsonSchemaDocument> = asObject;

const schemaRef: Decoder<SchemaRef> = (value, path) => {
	const f = new JsonFields(value, path);
	return { id: f.string('id'), name: f.string('name'), version: f.integer('version') };
};

const organization: Decoder<Organization> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		catalog_count: f.integer('catalog_count'),
		created_at: f.string('created_at'),
		created_by: f.string('created_by'),
		description: f.string('description'),
		display_name: f.string('display_name'),
		id: f.string('id'),
		name: f.string('name'),
		version: f.integer('version')
	};
};

const catalog: Decoder<Catalog> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		created_at: f.string('created_at'),
		created_by: f.string('created_by'),
		description: f.string('description'),
		display_name: f.string('display_name'),
		id: f.string('id'),
		name: f.string('name'),
		namespace_count: f.integer('namespace_count'),
		organization: f.string('organization'),
		schema: f.get('schema', schemaRef),
		version: f.integer('version')
	};
};

const namespace: Decoder<Namespace> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		catalog: f.string('catalog'),
		collection_count: f.integer('collection_count'),
		collections_allowed: f.boolean('collections_allowed'),
		created_at: f.string('created_at'),
		created_by: f.string('created_by'),
		disk_path: f.string('disk_path'),
		id: f.string('id'),
		identifier: f.string('identifier'),
		name: f.string('name'),
		namespace_count: f.integer('namespace_count'),
		organization: f.string('organization'),
		parent: f.string('parent'),
		path: f.string('path'),
		version: f.integer('version')
	};
};

const collectionProblem: Decoder<CollectionProblem> = (value, path) => {
	const f = new JsonFields(value, path);
	return { message: f.string('message'), path: f.string('path'), rule: f.string('rule') };
};

const collection: Decoder<Collection> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		activated_at: f.nullableString('activated_at'),
		catalog: f.string('catalog'),
		created_at: f.string('created_at'),
		created_by: f.string('created_by'),
		file_count: f.integer('file_count'),
		id: f.string('id'),
		identifier: f.string('identifier'),
		metadata: f.object('metadata'),
		name: f.string('name'),
		namespace: f.string('namespace'),
		organization: f.string('organization'),
		path: f.nullableString('path'),
		problems: f.get('problems', asArray(collectionProblem)),
		schema: f.get('schema', schemaRef),
		schema_override: f.nullableObject('schema_override'),
		state: f.string('state'),
		updated_at: f.string('updated_at'),
		version: f.integer('version')
	};
};

const fileRecord: Decoder<FileRecord> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		commit_id: f.string('commit_id'),
		recorded_at: f.string('recorded_at'),
		recorded_by: f.string('recorded_by'),
		rel_path: f.string('rel_path'),
		sha256: f.string('sha256'),
		size: f.integer('size')
	};
};

const commit: Decoder<Commit> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		actor: f.string('actor'),
		adds: f.integer('adds'),
		base_version: f.integer('base_version'),
		created_at: f.string('created_at'),
		host: f.string('host'),
		id: f.string('id'),
		message: f.nullableString('message'),
		new_version: f.integer('new_version'),
		removes: f.integer('removes')
	};
};

const auditEntry: Decoder<AuditEntry> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		action: f.string('action'),
		actor: f.string('actor'),
		at: f.string('at'),
		catalog_id: f.nullableString('catalog_id'),
		detail: f.object('detail'),
		id: f.nullableInteger('id'),
		object_id: f.nullableString('object_id'),
		object_type: f.string('object_type'),
		organization_id: f.nullableString('organization_id')
	};
};

const schemaEntry: Decoder<SchemaEntry> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		created_at: f.string('created_at'),
		created_by: f.string('created_by'),
		document: f.object('document'),
		extends_id: f.nullableString('extends_id'),
		id: f.string('id'),
		name: f.string('name'),
		organization_id: f.nullableString('organization_id'),
		scope: f.string('scope'),
		version: f.integer('version')
	};
};

const effectiveGroups: Decoder<EffectiveGroups> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		catalog_admin: f.strings('catalog_admin'),
		contributor: f.strings('contributor'),
		org_admin: f.strings('org_admin'),
		platform_admin: f.strings('platform_admin'),
		reader: f.strings('reader')
	};
};

const roleGrant: Decoder<RoleGrant> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		role: f.string('role'),
		scope: f.string('scope'),
		scope_id: f.nullableString('scope_id')
	};
};

const whoAmI: Decoder<WhoAmI> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		groups: f.strings('groups'),
		name: f.string('name'),
		roles: f.get('roles', asArray(roleGrant)),
		subject: f.string('subject')
	};
};

const exchangeOut: Decoder<ExchangeOut> = (value, path) => {
	const f = new JsonFields(value, path);
	return {
		expires_at: f.string('expires_at'),
		groups: f.strings('groups'),
		huron_token: f.string('huron_token'),
		name: f.string('name'),
		subject: f.string('subject')
	};
};
