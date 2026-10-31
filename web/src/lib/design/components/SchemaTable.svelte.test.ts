import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { MAX_SCHEMA_FIELDS, schemaView } from '$lib/schema-view';
import SchemaTable from './SchemaTable.svelte';

describe('SchemaTable', () => {
	it('lists a row per property, also beside a property named like a nested one', () => {
		render(SchemaTable, {
			props: {
				label: 'Fields of the schema',
				schema: schemaView({
					type: 'object',
					properties: {
						instrument: {
							type: 'object',
							title: 'Instrument',
							properties: { name: { type: 'string', title: 'Name' } }
						},
						'instrument/name': { type: 'string', title: 'Instrument and name' }
					}
				})
			}
		});
		const rows = within(screen.getByRole('table', { name: 'Fields of the schema' })).getAllByRole(
			'rowheader'
		);
		expect(rows).toHaveLength(3);
		expect(rows[0]).toHaveTextContent('Instrument instrument');
		expect(rows[1]).toHaveTextContent('Instrument › Name instrument/name');
		expect(rows[2]).toHaveTextContent('Instrument and name instrument~1name');
	});

	it('draws the first rows of a huge schema and says how many more it has, and that its JSON is cut', () => {
		const properties = Object.fromEntries(
			Array.from({ length: 20_000 }, (_, index) => [`p${String(index).padStart(5, '0')}`, {}])
		);
		render(SchemaTable, {
			props: { label: 'Fields of the override', schema: schemaView({ type: 'object', properties }) }
		});
		const table = screen.getByRole('table', { name: 'Fields of the override' });
		expect(within(table).getAllByRole('rowheader')).toHaveLength(MAX_SCHEMA_FIELDS);
		expect(
			screen.getByText('and 19,800 more fields: this schema is too long to show in full here.')
		).toBeInTheDocument();
		expect(
			screen.getByText('The document is too long to show in full here; this is its beginning.')
		).toBeInTheDocument();
	});

	it('draws rows whose shortened keys read alike', () => {
		const long = 'k'.repeat(5_000);
		render(SchemaTable, {
			props: {
				label: 'Fields',
				schema: schemaView({ type: 'object', properties: { [`${long}a`]: {}, [`${long}b`]: {} } })
			}
		});
		expect(within(screen.getByRole('table')).getAllByRole('rowheader')).toHaveLength(2);
		expect(screen.queryByText(/too long to show in full/)).toBeNull();
	});
});
