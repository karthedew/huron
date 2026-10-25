import type { PolarisProperties } from './polaris-types';

export type DatasetLayerId = 'bronze' | 'silver' | 'gold' | 'unassigned' | 'unknown' | 'conflict';

export interface DatasetLayer {
	id: DatasetLayerId;
	label: string;
	detail: string;
}

function processingLayer(value: string | undefined): 'bronze' | 'silver' | 'gold' | null {
	const normalized = value?.trim().toLowerCase();
	return normalized === 'bronze' || normalized === 'silver' || normalized === 'gold'
		? normalized
		: null;
}

/** Keep processing stage independent of storage format and surface conflicting declarations. */
export function datasetLayer(namespace: string[], properties?: PolarisProperties): DatasetLayer {
	const namespaceLayers = new Set(namespace.map(processingLayer).filter((layer) => layer !== null));
	const declaration = properties?.['huron.layer'];
	const declared = processingLayer(declaration);
	if (
		namespaceLayers.size > 1 ||
		(declaration !== undefined && !declared) ||
		(declared && namespaceLayers.size > 0 && !namespaceLayers.has(declared))
	) {
		return {
			id: 'conflict',
			label: 'Layer conflict',
			detail:
				'The huron.layer property and namespace must identify the same bronze, silver or gold stage.'
		};
	}
	const layer = declared ?? [...namespaceLayers][0];
	if (!layer && properties === undefined)
		return {
			id: 'unknown',
			label: 'Not loaded',
			detail:
				'Dataset layer metadata has not been loaded. Open the dataset to inspect its properties.'
		};
	if (!layer)
		return {
			id: 'unassigned',
			label: 'Unassigned',
			detail: 'No processing layer is recorded in huron.layer or the namespace.'
		};
	return {
		id: layer,
		label: layer[0].toUpperCase() + layer.slice(1),
		detail: declared
			? 'Recorded in the huron.layer dataset property.'
			: 'Declared by namespace placement; a dataset property has not been loaded or recorded.'
	};
}

export function datasetTypeLabel(dataset: { format?: string }): 'Generic' | 'Iceberg' | 'Icechunk' {
	if (dataset.format === 'raw') return 'Generic';
	if (dataset.format === 'iceberg') return 'Iceberg';
	return 'Icechunk';
}
