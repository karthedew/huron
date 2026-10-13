import type { PolarisProperties } from './polaris-types';

/** A generic-table identifier; `raw` selects Polaris's generic-table transport. */
export interface PolarisRawTableIdentifier {
	name: string;
	namespace: string[];
	format: 'raw';
	storageFormat: string | null;
	isRaw: boolean | null;
	properties?: PolarisProperties;
}

/** Registered metadata only: Polaris generic tables expose no Raw file manifest or revisions. */
export interface PolarisRawTable extends PolarisRawTableIdentifier {
	storageFormat: string;
	isRaw: boolean;
	location: string | null;
	doc: string;
	properties: PolarisProperties;
}
