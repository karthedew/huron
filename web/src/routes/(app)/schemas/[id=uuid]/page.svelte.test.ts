import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { schemaView } from '$lib/schema-view';
import { schemaSummary } from '$lib/schemas';
import { schemaFixture, organizationFixture } from '$lib/testing/api-fixtures';
import { catalogPageData } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

function show({ platform = false, unnamedOwner = false } = {}) {
	const authored = schemaView({ properties: { mission: { type: 'string' } } });
	const resolved = schemaView({
		properties: { title: { type: 'string' }, mission: { type: 'string' } }
	});
	render(Page, {
		props: {
			data: {
				...catalogPageData(),
				schemaOrganization: platform || unnamedOwner ? null : organizationFixture(),
				entry: schemaSummary(
					schemaFixture({
						name: 'space-weather',
						version: 2,
						organization_id: platform ? null : organizationFixture().id
					})
				),
				parentSchema: platform ? null : schemaSummary(schemaFixture()),
				authoredSchema: authored,
				resolvedSchema: resolved
			},
			params: { id: schemaFixture().id },
			form: undefined
		}
	});
}

describe('a schema version', () => {
	it('shows the source, exact parent version and resolved fields separately from the authored document', () => {
		show();
		expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('space-weather v2');
		expect(screen.getByText('Heliophysics Division')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'huron-base v1' })).toHaveAttribute(
			'href',
			`/schemas/${schemaFixture().id}`
		);
		const resolved = screen.getByRole('table', { name: 'Resolved schema fields' });
		expect(within(resolved).getAllByRole('rowheader')).toHaveLength(2);
		const authored = screen.getByText('Authored schema');
		expect(authored.tagName).toBe('SUMMARY');
		expect(authored.closest('details')).not.toHaveAttribute('open');
		expect(screen.getByRole('link', { name: 'Back to schemas' })).toHaveAttribute(
			'href',
			'/schemas?organization=helio'
		);
		expect(document.title).toBe('space-weather v2 · Schemas · Huron');
	});

	it('identifies a platform base version and returns to platform versions', () => {
		show({ platform: true });
		expect(screen.getByText('Platform')).toBeInTheDocument();
		expect(screen.getByText('Base schema')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Back to schemas' })).toHaveAttribute(
			'href',
			'/schemas?organization='
		);
	});

	it('does not call an organization schema a platform schema when its owner is beyond the source list', () => {
		show({ unnamedOwner: true });
		expect(screen.getByText('Organization')).toBeInTheDocument();
		expect(screen.queryByText('Platform')).toBeNull();
		expect(screen.getByRole('link', { name: 'Choose organization' })).toHaveAttribute(
			'href',
			'/orgs'
		);
	});
});
