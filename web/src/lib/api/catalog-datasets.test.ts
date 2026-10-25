import { describe, expect, it } from 'vitest';
import { datasetLayer, datasetTypeLabel } from './catalog-datasets';

describe('dataset processing layers', () => {
	it('does not infer a layer from a storage format or scientific domain', () => {
		expect(datasetLayer(['heliophysics', 'raw'], { format: 'icechunk' }).id).toBe('unassigned');
	});
	it('reads an explicit processing-stage namespace', () => {
		expect(datasetLayer(['device_2', 'silver'], {}).id).toBe('silver');
	});
	it('reads recorded metadata independently of format', () => {
		expect(datasetLayer(['observations'], { 'huron.layer': 'gold' }).id).toBe('gold');
	});
	it('accepts matching metadata and placement', () => {
		expect(datasetLayer(['device_2', 'Bronze'], { 'huron.layer': 'bronze' }).id).toBe('bronze');
	});
	it('marks metadata and namespace disagreements', () => {
		expect(datasetLayer(['silver'], { 'huron.layer': 'gold' }).id).toBe('conflict');
	});
	it('marks ambiguous namespace stages and invalid declarations', () => {
		expect(datasetLayer(['bronze', 'silver'], {}).id).toBe('conflict');
		expect(datasetLayer(['bronze'], { 'huron.layer': 'raw' }).id).toBe('conflict');
	});
	it('explains when only namespace information was loaded', () => {
		expect(datasetLayer(['observations']).id).toBe('unknown');
		expect(datasetLayer(['observations']).label).toBe('Not loaded');
		expect(datasetLayer(['observations']).detail).toContain('Open the dataset');
	});
	it('distinguishes absent metadata from loaded metadata with no processing stage', () => {
		expect(datasetLayer(['observations'], {}).id).toBe('unassigned');
		expect(datasetLayer(['observations'], { 'huron.layer': 'bronze' }).id).toBe('bronze');
		expect(datasetLayer(['observations', 'bronze']).id).toBe('bronze');
	});
	it('keeps dataset type labels separate from layer labels', () => {
		expect(datasetTypeLabel({ format: 'raw' })).toBe('Generic');
		expect(datasetTypeLabel({ format: 'iceberg' })).toBe('Iceberg');
		expect(datasetTypeLabel({})).toBe('Icechunk');
	});
});
