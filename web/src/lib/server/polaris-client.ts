import type {
	PolarisCatalog,
	PolarisCatalogTable,
	PolarisCredentialSummary,
	PolarisGrant,
	PolarisIcechunkTable,
	PolarisIcebergTable,
	PolarisNamedEntity,
	PolarisPrincipal,
	PolarisProperties,
	PolarisGenericTable,
	PolarisGenericTableIdentifier,
	PolarisRole,
	PolarisStorageConfig
} from '$api/types';
import { icebergTable, parseIcebergResponseJson } from './polaris-iceberg';
import { genericTable } from './polaris-generic';

export class PolarisApiError extends Error {
	constructor(
		public readonly status: number,
		message = statusMessage(status)
	) {
		super(message);
	}
}

function statusMessage(status: number): string {
	switch (status) {
		case 400:
			return 'Polaris rejected the request. Check the properties and storage configuration.';
		case 401:
			return 'Polaris credentials are invalid or expired. Reconnect with your principal credentials.';
		case 403:
			return 'Your Polaris principal does not have permission for this action.';
		case 404:
			return 'Resource not found.';
		case 406:
			return 'This Polaris service has not enabled the requested operation.';
		case 409:
			return 'The resource already exists or has changed. Refresh before retrying.';
		case 502:
			return 'Polaris returned an invalid response.';
		default:
			return 'Polaris is unavailable. Check that the configured server is running.';
	}
}

export function object(value: unknown): Record<string, unknown> {
	if (typeof value !== 'object' || value === null || Array.isArray(value))
		throw new PolarisApiError(502);
	return Object.fromEntries(Object.entries(value));
}

function text(value: unknown): string {
	if (typeof value !== 'string') throw new PolarisApiError(502);
	return value;
}

export function strings(value: unknown): string[] {
	if (!Array.isArray(value)) throw new PolarisApiError(502);
	return value.map(text);
}

export function properties(value: unknown): PolarisProperties {
	if (value === undefined || value === null) return {};
	return Object.fromEntries(
		Object.entries(object(value)).map(([key, entry]) => [key, text(entry)])
	);
}

function list<T>(value: unknown, key: string, decode: (value: unknown) => T): T[] {
	const entries = object(value)[key];
	if (!Array.isArray(entries)) throw new PolarisApiError(502);
	return entries.map(decode);
}

function named(value: unknown): PolarisNamedEntity {
	const entry = object(value);
	return {
		name: text(entry.name),
		properties: properties(entry.properties),
		...(typeof entry.entityVersion === 'number' ? { entityVersion: entry.entityVersion } : {})
	};
}

export function storageConfig(value: unknown): PolarisStorageConfig {
	const entry = object(value);
	const storageType = entry.storageType;
	if (
		storageType !== 'FILE' &&
		storageType !== 'S3' &&
		storageType !== 'GCS' &&
		storageType !== 'AZURE'
	)
		throw new PolarisApiError(502);
	const result: PolarisStorageConfig = { storageType };
	for (const [key, field] of Object.entries(entry)) {
		if (key === '__proto__' || key === 'constructor' || key === 'prototype')
			throw new PolarisApiError(502);
		if (typeof field === 'string' || typeof field === 'boolean' || typeof field === 'number')
			result[key] = field;
		else if (Array.isArray(field)) result[key] = strings(field);
		else if (field !== null && field !== undefined) throw new PolarisApiError(502);
	}
	return result;
}

export function catalog(value: unknown): PolarisCatalog {
	const entry = object(value);
	if (entry.type !== 'INTERNAL' && entry.type !== 'EXTERNAL') throw new PolarisApiError(502);
	return {
		...named(entry),
		type: entry.type,
		storageConfigInfo: storageConfig(entry.storageConfigInfo)
	};
}

export function principal(value: unknown): PolarisPrincipal {
	const entry = object(value);
	return {
		...named(entry),
		...(typeof entry.clientId === 'string' ? { clientId: entry.clientId } : {})
	};
}

export function role(value: unknown): PolarisRole {
	const entry = object(value);
	return {
		...named(entry),
		...(typeof entry.federated === 'boolean' ? { federated: entry.federated } : {})
	};
}

export function table(value: unknown): PolarisIcechunkTable {
	const entry = object(value);
	return {
		name: text(entry.name),
		location: text(entry.location),
		properties: properties(entry.properties)
	};
}

function grant(value: unknown): PolarisGrant {
	const entry = object(value);
	return {
		type: text(entry.type),
		privilege: text(entry.privilege),
		...(entry.namespace !== undefined ? { namespace: strings(entry.namespace) } : {}),
		...(typeof entry.tableName === 'string' ? { tableName: entry.tableName } : {}),
		...(typeof entry.viewName === 'string' ? { viewName: entry.viewName } : {}),
		...(typeof entry.policyName === 'string' ? { policyName: entry.policyName } : {}),
		...(typeof entry.semanticModelName === 'string'
			? { semanticModelName: entry.semanticModelName }
			: {})
	};
}

export function credentialSummary(
	value: unknown,
	accessMode: 'read' | 'read-write',
	delegated: boolean
): PolarisCredentialSummary {
	const entries = object(value)['storage-access-configs'] ?? [];
	if (!Array.isArray(entries)) throw new PolarisApiError(502);
	const configurations = entries.map((value) => {
		const entry = object(value);
		const config = properties(entry.config);
		const expiry = Object.entries(config).find(([key]) => /expires-at/.test(key))?.[1];
		let expiresAt: string | null = null;
		if (expiry) {
			const date = /^\d+$/.test(expiry) ? new Date(Number(expiry)) : new Date(expiry);
			if (Number.isFinite(date.getTime())) expiresAt = date.toISOString();
		}
		return {
			prefix: text(entry.prefix),
			hasCredentials: Object.keys(config).some(
				(key) => !/expires|refresh/.test(key) && /secret|token|access-key/.test(key)
			),
			expiresAt
		};
	});
	return {
		accessMode,
		delegated,
		configurations,
		message: configurations.length
			? 'Polaris vended storage credentials. Secret values remain on the server.'
			: delegated
				? 'No credentials were vended. FILE storage does not support credential vending.'
				: 'Repository metadata loaded without credential delegation.'
	};
}

export interface PolarisConnection {
	url: string;
	realm: string;
	clientId: string;
	clientSecret: string;
}

interface Token {
	value: string;
	expiresAt: number;
}

/** Holds principal authentication and protocol details behind server-only operations. */
export class PolarisClient {
	private token: Token | null = null;
	private pendingToken: Promise<Token> | null = null;

	constructor(
		private readonly credentials: PolarisConnection,
		private readonly fetcher: typeof fetch = fetch
	) {}

	/** Connection identity for server routing; privileged credentials remain private. */
	get connection(): Readonly<Pick<PolarisConnection, 'url' | 'realm'>> {
		return { url: this.credentials.url, realm: this.credentials.realm };
	}

	async authenticate(): Promise<void> {
		await this.accessToken();
	}

	private async accessToken(): Promise<Token> {
		if (this.token && this.token.expiresAt > Date.now() + 15_000) return this.token;
		if (this.pendingToken) return this.pendingToken;
		this.pendingToken = this.exchangeToken();
		try {
			this.token = await this.pendingToken;
			return this.token;
		} finally {
			this.pendingToken = null;
		}
	}

	private async exchangeToken(): Promise<Token> {
		const body = new URLSearchParams({
			grant_type: 'client_credentials',
			client_id: this.credentials.clientId,
			client_secret: this.credentials.clientSecret,
			scope: 'PRINCIPAL_ROLE:ALL'
		});
		const response = await this.send('/api/catalog/v1/oauth/tokens', {
			method: 'POST',
			headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
			body
		});
		if (!response.ok) throw new PolarisApiError(response.status === 400 ? 401 : response.status);
		const result = object(await this.json(response));
		return {
			value: text(result.access_token),
			expiresAt:
				Date.now() + (typeof result.expires_in === 'number' ? result.expires_in : 300) * 1000
		};
	}

	private async send(path: string, init: RequestInit): Promise<Response> {
		try {
			const headers = new Headers(init.headers);
			headers.set('Polaris-Realm', this.connection.realm);
			return await this.fetcher(`${this.connection.url}${path}`, {
				...init,
				headers,
				redirect: 'error',
				signal: AbortSignal.timeout(10_000)
			});
		} catch {
			throw new PolarisApiError(503);
		}
	}

	private async json(response: Response): Promise<unknown> {
		try {
			return await response.json();
		} catch {
			throw new PolarisApiError(502);
		}
	}

	async request(
		path: string,
		method = 'GET',
		body?: unknown,
		extraHeaders?: Record<string, string>,
		discover = false,
		preserveSnapshotIds = false
	): Promise<unknown> {
		let token = await this.accessToken();
		const init = () => ({
			method,
			headers: {
				Authorization: `Bearer ${token.value}`,
				...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
				...extraHeaders
			},
			...(body === undefined ? {} : { body: JSON.stringify(body) })
		});
		let response = await this.send(path, init());
		if (response.status === 401) {
			this.token = null;
			token = await this.accessToken();
			response = await this.send(path, init());
		}
		if (!response.ok)
			throw new PolarisApiError(discover && response.status === 403 ? 404 : response.status);
		if (response.status === 204 || response.headers.get('content-length') === '0') return {};
		const content = await response.text();
		if (!content) return {};
		try {
			const result: unknown = preserveSnapshotIds
				? parseIcebergResponseJson(content)
				: JSON.parse(content);
			return result;
		} catch {
			throw new PolarisApiError(502);
		}
	}

	async catalogs(): Promise<PolarisCatalog[]> {
		return list(
			await this.request('/api/management/v1/catalogs', 'GET', undefined, undefined, true),
			'catalogs',
			catalog
		);
	}
	async catalog(name: string): Promise<PolarisCatalog> {
		return catalog(await this.read(management('catalogs', name)));
	}
	async principals(): Promise<PolarisPrincipal[]> {
		return list(await this.read(management('principals')), 'principals', principal);
	}
	async principalRoles(): Promise<PolarisRole[]> {
		return list(await this.read(management('principal-roles')), 'roles', role);
	}
	async catalogRoles(name: string): Promise<PolarisRole[]> {
		return list(await this.read(management('catalogs', name, 'catalog-roles')), 'roles', role);
	}
	async memberships(name: string): Promise<PolarisRole[]> {
		return list(await this.read(management('principals', name, 'principal-roles')), 'roles', role);
	}
	async assignments(principalRole: string, name: string): Promise<PolarisRole[]> {
		return list(
			await this.read(management('principal-roles', principalRole, 'catalog-roles', name)),
			'roles',
			role
		);
	}
	async grants(name: string, catalogRole: string): Promise<PolarisGrant[]> {
		return list(
			await this.read(management('catalogs', name, 'catalog-roles', catalogRole, 'grants')),
			'grants',
			grant
		);
	}
	async namespaces(
		name: string,
		parent: string[] = [],
		pageToken = ''
	): Promise<{ namespaces: string[][]; nextPageToken: string | null }> {
		const query = new URLSearchParams({ pageSize: '100' });
		if (parent.length) query.set('parent', parent.join('\x1f'));
		if (pageToken) query.set('pageToken', pageToken);
		const value = await this.read(`${namespacePath(name)}?${query}`);
		const next = object(value)['next-page-token'];
		return {
			namespaces: list(value, 'namespaces', strings),
			nextPageToken: typeof next === 'string' && next ? next : null
		};
	}
	async namespaceProperties(name: string, namespace: string[]): Promise<PolarisProperties> {
		return properties(object(await this.read(namespacePath(name, namespace))).properties);
	}
	async tables(
		name: string,
		namespace: string[],
		pageToken = ''
	): Promise<{ tables: PolarisIcechunkTable[]; nextPageToken: string | null }> {
		const query = new URLSearchParams({ pageSize: '100' });
		if (pageToken) query.set('pageToken', pageToken);
		const value = await this.read(`${icechunkPath(name, namespace)}?${query}`);
		const tables = list(value, 'identifiers', (value) => {
			const entry = object(value);
			return {
				name: text(entry.name),
				location: '',
				properties: {},
				namespace: strings(entry.namespace)
			};
		});
		const next = object(value)['next-page-token'];
		return { tables, nextPageToken: typeof next === 'string' && next ? next : null };
	}
	async table(name: string, namespace: string[], tableName: string): Promise<PolarisIcechunkTable> {
		return table(object(await this.read(icechunkPath(name, namespace, tableName))).table);
	}
	async icebergTables(
		name: string,
		namespace: string[],
		pageToken = ''
	): Promise<{ tables: PolarisCatalogTable[]; nextPageToken: string | null }> {
		const query = new URLSearchParams({ pageSize: '100' });
		if (pageToken) query.set('pageToken', pageToken);
		const value = await this.read(`${icebergPath(name, namespace)}?${query}`);
		const next = object(value)['next-page-token'];
		return {
			tables: list(value, 'identifiers', (value) => {
				const entry = object(value);
				return { name: text(entry.name), namespace: strings(entry.namespace), format: 'iceberg' };
			}),
			nextPageToken: typeof next === 'string' && next ? next : null
		};
	}
	async icebergTable(
		name: string,
		namespace: string[],
		tableName: string
	): Promise<PolarisIcebergTable> {
		const value = await this.request(
			icebergPath(name, namespace, tableName),
			'GET',
			undefined,
			undefined,
			true,
			true
		);
		try {
			return icebergTable(value, namespace, tableName);
		} catch {
			throw new PolarisApiError(502, 'Polaris returned invalid Iceberg scientific metadata.');
		}
	}
	async genericTables(
		name: string,
		namespace: string[],
		pageToken = ''
	): Promise<{ tables: PolarisGenericTableIdentifier[]; nextPageToken: string | null }> {
		const query = new URLSearchParams({ pageSize: '100' });
		if (pageToken) query.set('pageToken', pageToken);
		const value = await this.read(`${genericTablePath(name, namespace)}?${query}`);
		const next = object(value)['next-page-token'];
		const identifiers = list(value, 'identifiers', (value): PolarisGenericTableIdentifier => {
			const entry = object(value);
			return {
				name: text(entry.name),
				namespace: strings(entry.namespace),
				format: 'generic',
				storageFormat: null
			};
		});
		const tables: PolarisGenericTableIdentifier[] = [];
		// Generic identifiers have no format; resolve it using the same user's metadata authority.
		for (let index = 0; index < identifiers.length; index += 8) {
			tables.push(
				...(await Promise.all(
					identifiers.slice(index, index + 8).map(async (identifier) => {
						try {
							const loaded = await this.genericTable(name, identifier.namespace, identifier.name);
							return {
								...identifier,
								storageFormat: loaded.storageFormat,
								properties: loaded.properties
							};
						} catch (error) {
							if (error instanceof PolarisApiError && error.status === 404) return identifier;
							throw error;
						}
					})
				))
			);
		}
		return { tables, nextPageToken: typeof next === 'string' && next ? next : null };
	}
	async genericTable(
		name: string,
		namespace: string[],
		tableName: string
	): Promise<PolarisGenericTable> {
		const value = await this.read(genericTablePath(name, namespace, tableName));
		try {
			return genericTable(value, namespace, tableName);
		} catch {
			throw new PolarisApiError(502, 'Polaris returned invalid generic-table metadata.');
		}
	}
	private read(path: string): Promise<unknown> {
		return this.request(path, 'GET', undefined, undefined, true);
	}
}

export function management(...segments: string[]): string {
	return `/api/management/v1/${segments.map(encodeURIComponent).join('/')}`;
}

export function namespacePath(name: string, namespace: string[] = []): string {
	return `/api/catalog/v1/${encodeURIComponent(name)}/namespaces${namespace.length ? '/' + encodeURIComponent(namespace.join('\x1f')) : ''}`;
}

export function icechunkPath(name: string, namespace: string[], tableName = ''): string {
	return `/api/catalog/polaris/v1/${encodeURIComponent(name)}/namespaces/${encodeURIComponent(namespace.join('\x1f'))}/icechunk-tables${tableName ? '/' + encodeURIComponent(tableName) : ''}`;
}

export function icebergPath(name: string, namespace: string[], tableName = ''): string {
	return `${namespacePath(name, namespace)}/tables${tableName ? '/' + encodeURIComponent(tableName) : ''}`;
}

export function genericTablePath(name: string, namespace: string[], tableName = ''): string {
	return `/api/catalog/polaris/v1/${encodeURIComponent(name)}/namespaces/${encodeURIComponent(namespace.join('\x1f'))}/generic-tables${tableName ? '/' + encodeURIComponent(tableName) : ''}`;
}
