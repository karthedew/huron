import type { PolarisIcechunkTable, PolarisWorkspaceData } from './polaris-types';
import type { IcechunkInspection } from './icechunk-types';
import type { PolarisGenericTable, PolarisGenericTableIdentifier } from './polaris-generic-types';
import type {
	PolarisCatalogTable,
	PolarisDatasetGovernance,
	PolarisIcebergTable
} from './polaris-governance-types';

/** One lazily loaded folder in the selected catalog's namespace hierarchy. */
export interface PolarisBrowseBranch {
	namespace: string[];
	folders: string[][];
	repositories: (PolarisIcechunkTable | PolarisCatalogTable | PolarisGenericTableIdentifier)[];
	namespacePageToken: string | null;
	repositoryPageToken: string | null;
	icebergPageToken: string | null;
	genericPageToken: string | null;
	nextNamespacePageToken: string | null;
	nextRepositoryPageToken: string | null;
	nextIcebergPageToken: string | null;
	nextGenericPageToken: string | null;
	errors: Record<string, string>;
}

export interface PolarisBrowseData extends PolarisWorkspaceData {
	branches: PolarisBrowseBranch[];
	inspection: IcechunkInspection | null;
	governance: PolarisDatasetGovernance | null;
	icebergTables: PolarisCatalogTable[];
	nextIcebergPageToken: string | null;
	loadedIcebergTable: PolarisIcebergTable | null;
	genericTables: PolarisGenericTableIdentifier[];
	nextGenericPageToken: string | null;
	loadedGenericTable: PolarisGenericTable | null;
}
