import { describe, expect, it } from 'vitest';
import { SCHEMA_TEXT_LENGTH } from './schema-view';
import { schemaSummary } from './schemas';
import { schemaFixture } from './testing/api-fixtures';
import { serializePageData } from './testing/page-data';

describe('schemaSummary', () => {
	it('keeps identity, ownership, inheritance and publication fields without the document', () => {
		const summary = schemaSummary(schemaFixture());
		expect(summary).toEqual({
			id: schemaFixture().id,
			name: 'huron-base',
			version: 1,
			organizationId: null,
			extendsId: null,
			createdAt: schemaFixture().created_at,
			createdBy: 'sub-alice'
		});
		expect(
			schemaSummary(schemaFixture({ organization_id: 'organization', extends_id: 'parent' }))
		).toMatchObject({ organizationId: 'organization', extendsId: 'parent' });
	});

	it('bounds text by code points and preserves empty text', () => {
		const value = '🪐'.repeat(SCHEMA_TEXT_LENGTH + 1);
		const summary = schemaSummary(
			schemaFixture({ name: value, created_by: value, created_at: value })
		);
		for (const text of [summary.name, summary.createdBy, summary.createdAt]) {
			expect([...text]).toHaveLength(SCHEMA_TEXT_LENGTH + 1);
			expect(text.endsWith('…')).toBe(true);
		}
		expect(schemaSummary(schemaFixture({ name: '', created_by: '' }))).toMatchObject({
			name: '',
			createdBy: ''
		});
	});

	it('never sends user-chosen document keys as page data keys', () => {
		const summary = schemaSummary(
			schemaFixture({ document: { ['__proto__']: { type: 'string' } } })
		);
		expect(() => serializePageData(summary)).not.toThrow();
		expect(summary).not.toHaveProperty('document');
	});
});
