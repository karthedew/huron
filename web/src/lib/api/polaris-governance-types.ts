import type { PolarisGrant, PolarisProperties } from './polaris-types';

export type PolarisTableFormat = 'icechunk' | 'iceberg' | 'raw';

export interface PolarisCatalogTable {
	name: string;
	namespace: string[];
	format: 'iceberg';
}

export interface PolarisIcebergField {
	id: number;
	name: string;
	required: boolean;
	type: PolarisIcebergFieldType;
	doc?: string;
}

export type PolarisIcebergFieldType =
	| string
	| {
			type: 'struct';
			fields: PolarisIcebergField[];
	  }
	| {
			type: 'list';
			elementId: number;
			elementRequired: boolean;
			element: PolarisIcebergFieldType;
	  }
	| {
			type: 'map';
			keyId: number;
			key: PolarisIcebergFieldType;
			valueId: number;
			valueRequired: boolean;
			value: PolarisIcebergFieldType;
	  };

export interface PolarisIcebergSchema {
	schemaId: number;
	identifierFieldIds: number[];
	fields: PolarisIcebergField[];
}

export interface PolarisIcebergSnapshot {
	snapshotId: string;
	parentSnapshotId: string | null;
	timestampMs: number;
	schemaId: number | null;
	manifestList: string | null;
	summary: Record<string, string>;
}

export interface PolarisIcebergRef {
	type: 'branch' | 'tag';
	snapshotId: string;
	minSnapshotsToKeep?: number;
	maxSnapshotAgeMs?: number;
	maxRefAgeMs?: number;
}

/** Scientific Iceberg metadata; response configuration and credentials are excluded. */
export interface PolarisIcebergTable extends PolarisCatalogTable {
	location: string;
	properties: PolarisProperties;
	metadataLocation: string | null;
	tableUuid: string | null;
	formatVersion: number;
	currentSchemaId: number;
	currentSnapshotId: string | null;
	schemas: PolarisIcebergSchema[];
	snapshots: PolarisIcebergSnapshot[];
	refs: Record<string, PolarisIcebergRef>;
	snapshotLog: { timestampMs: number; snapshotId: string }[];
	metadataLog: { timestampMs: number; metadataFile: string }[];
}

export interface PolarisDatasetTarget {
	catalog: string;
	namespace: string[];
	table: string;
	format: PolarisTableFormat;
}

export interface PolarisDatasetGrant {
	catalogRole: string;
	principalRoles: string[];
	grant: PolarisGrant;
	inherited: boolean;
	scopeLabel: string;
}

export interface PolarisDatasetPermissions {
	principal: string;
	principalRoles: string[];
	catalogRoles: string[];
	applicableGrants: PolarisDatasetGrant[];
	visibility: 'self' | 'catalog';
	capabilities: {
		readMetadata: boolean;
		readData: boolean;
		writeData: boolean;
		manageAccess: boolean;
	};
	notice: string;
	error: string | null;
}

export interface PolarisApplicablePolicy {
	name: string;
	namespace: string[];
	policyType: string;
	version: number;
	inheritable: boolean;
	inherited: boolean;
	description: string;
}

export interface PolarisDatasetPolicies {
	supported: boolean;
	message: string;
	policies: PolarisApplicablePolicy[];
	nextPageToken: string | null;
	error: string | null;
}

export interface PolarisDatasetGovernance {
	permissions: PolarisDatasetPermissions;
	policies: PolarisDatasetPolicies;
}
