/** Browser-safe projections of the local Polaris OpenAPI contracts. */
export type PolarisProperties = Record<string, string>;

export interface PolarisNamedEntity {
	name: string;
	properties: PolarisProperties;
	entityVersion?: number;
}

export interface PolarisStorageConfig {
	storageType: 'FILE' | 'S3' | 'GCS' | 'AZURE';
	allowedLocations?: string[];
	[key: string]: string | number | boolean | string[] | undefined;
}

export interface PolarisCatalog extends PolarisNamedEntity {
	type: 'INTERNAL' | 'EXTERNAL';
	storageConfigInfo: PolarisStorageConfig;
}

export interface PolarisPrincipal extends PolarisNamedEntity {
	clientId?: string;
}

export interface PolarisRole extends PolarisNamedEntity {
	federated?: boolean;
}

export interface PolarisIcechunkTable {
	format?: 'icechunk';
	name: string;
	location: string;
	properties: PolarisProperties;
	namespace?: string[];
}

export interface PolarisGrant {
	type: string;
	privilege: string;
	namespace?: string[];
	tableName?: string;
	viewName?: string;
	policyName?: string;
	semanticModelName?: string;
}

export interface PolarisCredentialSummary {
	accessMode: 'read' | 'read-write';
	delegated: boolean;
	configurations: { prefix: string; hasCredentials: boolean; expiresAt: string | null }[];
	message: string;
}

export interface PolarisWorkspaceData {
	connected: boolean;
	upstream: string;
	realm: string;
	session: { clientId: string } | null;
	notice: string | null;
	catalogs: PolarisCatalog[];
	catalog: PolarisCatalog | null;
	namespaces: string[][];
	nextNamespacePageToken: string | null;
	namespaceProperties: PolarisProperties | null;
	tables: PolarisIcechunkTable[];
	nextPageToken: string | null;
	principals: PolarisPrincipal[];
	principalRoles: PolarisRole[];
	catalogRoles: PolarisRole[];
	principalMemberships: PolarisRole[];
	catalogAssignments: PolarisRole[];
	grants: PolarisGrant[];
	loadedTable: PolarisIcechunkTable | null;
	errors: Record<string, string>;
	selected: {
		catalog: string;
		namespace: string[];
		principal: string;
		principalRole: string;
		catalogRole: string;
		table: string;
	};
	privileges: { catalog: string[]; namespace: string[]; table: string[] };
}

export type PolarisActionResult = {
	action: string;
	success: boolean;
	message: string;
	status?: number;
	table?: PolarisIcechunkTable;
	credentialSummary?: PolarisCredentialSummary;
	/** Returned only by an explicitly submitted create/rotate/reset action. */
	credentials?: { clientId: string; clientSecret: string; principal: string };
};
