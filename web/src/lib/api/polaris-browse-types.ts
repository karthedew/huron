import type { PolarisIcechunkTable, PolarisWorkspaceData } from './polaris-types';
import type { IcechunkInspection } from './icechunk-types';
import type { RawInspection } from './raw-ingestion-types';
import type { PolarisRawTable, PolarisRawTableIdentifier } from './polaris-raw-types';
import type {
	PolarisCatalogTable,
	PolarisDatasetGovernance,
	PolarisIcebergTable
} from './polaris-governance-types';

/** One lazily loaded folder in the selected catalog's namespace hierarchy. */
export interface PolarisBrowseBranch {
	namespace: string[];
	folders: string[][];
	repositories: (PolarisIcechunkTable | PolarisCatalogTable | PolarisRawTableIdentifier)[];
	namespacePageToken: string | null;
	repositoryPageToken: string | null;
	icebergPageToken: string | null;
	rawPageToken: string | null;
	nextNamespacePageToken: string | null;
	nextRepositoryPageToken: string | null;
	nextIcebergPageToken: string | null;
	nextRawPageToken: string | null;
	errors: Record<string, string>;
}

export interface PolarisBrowseData extends PolarisWorkspaceData {
	branches: PolarisBrowseBranch[];
	inspection: IcechunkInspection | null;
	governance: PolarisDatasetGovernance | null;
	icebergTables: PolarisCatalogTable[];
	nextIcebergPageToken: string | null;
	loadedIcebergTable: PolarisIcebergTable | null;
	rawTables: PolarisRawTableIdentifier[];
	nextRawPageToken: string | null;
	loadedRawTable: PolarisRawTable | null;
	rawInspection: RawInspection | null;
}
