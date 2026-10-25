import type { PolarisProperties } from './polaris-types';

/** A Polaris generic-table identifier; `'generic'` selects the generic-table transport only. */
export interface PolarisGenericTableIdentifier {
	name: string;
	namespace: string[];
	format: 'generic';
	storageFormat: string | null;
	properties?: PolarisProperties;
}

/** Registered metadata only: generic tables expose no manifest, files or history. */
export interface PolarisGenericTable extends PolarisGenericTableIdentifier {
	storageFormat: string;
	location: string | null;
	doc: string;
	properties: PolarisProperties;
}
