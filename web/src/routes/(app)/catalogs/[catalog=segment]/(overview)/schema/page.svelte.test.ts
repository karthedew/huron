import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { JsonSchemaDocument } from '$api/types';
import { schemaView } from '$lib/schema-view';
import { catalogPageData } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

const SCHEMA: JsonSchemaDocument = {
	type: 'object',
	title: 'Huron base metadata',
	description: 'Fields every collection carries.',
	additionalProperties: true,
	required: ['title'],
	properties: {
		title: { type: 'string', title: 'Title', minLength: 1, maxLength: 200 },
		contacts: {
			type: 'array',
			title: 'Contacts',
			items: {
				type: 'object',
				required: ['name'],
				properties: { name: { type: 'string' }, email: { type: 'string', format: 'email' } }
			}
		},
		labels: {
			type: 'object',
			title: 'Labels',
			description: 'Free-form string labels used for search.',
			additionalProperties: { type: 'string' }
		}
	}
};

function show(schema = SCHEMA) {
	render(Page, {
		props: {
			data: { ...catalogPageData(), schema: schemaView(schema) },
			params: { catalog: 'heliophysics' },
			form: undefined
		}
	});
}

describe('the catalog schema tab', () => {
	it('names the schema and lists its fields in a table that scrolls on its own', () => {
		show();
		expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Schema huron-base v1');
		expect(screen.getByText('Huron base metadata')).toBeInTheDocument();
		const region = screen.getByRole('region', { name: "Fields of the catalog's schema" });
		expect(region).toHaveAttribute('tabindex', '0');
		const table = within(region).getByRole('table', { name: "Fields of the catalog's schema" });
		const headers = within(table)
			.getAllByRole('columnheader')
			.map((cell) => cell.textContent);
		expect(headers).toEqual(['Field', 'Type', 'Required', 'Constraints', 'Description']);
		const rows = within(table)
			.getAllByRole('rowheader')
			.map((cell) => cell.textContent?.replace(/\s+/g, ' ').trim());
		expect(rows).toEqual([
			'Title title',
			'Contacts contacts',
			'Contacts › name contacts/name',
			'Contacts › email contacts/email',
			'Labels labels'
		]);
		expect(document.title).toBe('Schema · Heliophysics · Huron');
	});

	it('shows what each field requires and accepts', () => {
		show();
		const [, title, contacts, name, email, labels] = within(screen.getByRole('table')).getAllByRole(
			'row'
		);
		expect(title).toHaveTextContent('string');
		expect(title).toHaveTextContent('Required');
		expect(title).toHaveTextContent('1 to 200 characters');
		expect(contacts).toHaveTextContent('array of objects');
		expect(contacts).toHaveTextContent('Optional');
		expect(name).toHaveTextContent('Required');
		expect(email).toHaveTextContent('format email');
		expect(labels).toHaveTextContent('each value: string');
		expect(labels).toHaveTextContent('Free-form string labels used for search.');
		expect(screen.getByText('Metadata may hold other fields as well.')).toBeInTheDocument();
	});

	it('keeps the raw JSON in a disclosure', () => {
		show();
		const raw = screen.getByText('Raw JSON');
		expect(raw.tagName).toBe('SUMMARY');
		const code = raw.closest('details')?.querySelector('pre code');
		expect(JSON.parse(code?.textContent ?? '')).toEqual(SCHEMA);
	});

	it('says when a schema names no fields', () => {
		show({ type: 'object' });
		expect(screen.getByText('This schema names no fields.')).toBeInTheDocument();
		expect(screen.queryByRole('table')).toBeNull();
	});
});
