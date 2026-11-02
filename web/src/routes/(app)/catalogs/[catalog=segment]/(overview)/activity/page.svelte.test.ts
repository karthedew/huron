import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AuditEntry } from '$api/types';
import type { SchemaName } from '$lib/activity';
import { auditFixture } from '$lib/testing/api-fixtures';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData } from '$lib/testing/catalog-data';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

afterEach(() => {
	resetAppState();
});

const BASE = '0192f2a4-0000-7000-8000-000000000201';
const ENTRIES: AuditEntry[] = [
	auditFixture({
		id: 3,
		action: 'collection.commit',
		at: '2026-10-29T10:15:30+00:00',
		actor: 'dave'
	}),
	auditFixture({
		id: 2,
		action: 'collection.create',
		detail: { identifier: 'heliophysics.fields.run001' }
	}),
	auditFixture({
		id: 1,
		action: 'namespace.create',
		object_type: 'namespace',
		detail: { path: 'solar-wind.ace' }
	}),
	auditFixture({
		id: 0,
		action: 'catalog.assign_schema',
		object_type: 'catalog',
		detail: { schema_id: BASE, previous: BASE }
	})
];

async function show(
	entries: AuditEntry[],
	{
		nextCursor = null,
		path = '/catalogs/heliophysics/activity',
		schemas = { [BASE]: { name: 'huron-base', version: 1 } }
	}: { nextCursor?: string | null; path?: string; schemas?: Record<string, SchemaName> } = {}
) {
	page.url = new URL(`http://localhost:4173${path}`);
	render(Page, {
		props: {
			data: { ...catalogPageData(), entries, nextCursor, schemas },
			params: { catalog: 'heliophysics' },
			form: undefined
		}
	});
	await tick();
}

function entries() {
	return within(screen.getByRole('list', { name: 'Catalog activity' })).getAllByRole('listitem');
}

describe('the catalog activity tab', () => {
	it('lists the entries with their label, summary, actor and UTC time', async () => {
		await show(ENTRIES);
		const [commit] = entries();
		expect(commit).toHaveTextContent('Committed files');
		expect(commit).toHaveTextContent(
			'3 added, 0 removed · from ws-17 · revision 2 · “First upload”'
		);
		expect(within(commit).getByText('dave')).toBeInTheDocument();
		const time = within(commit).getByText('2026-10-29 10:15 UTC');
		expect(time.tagName).toBe('TIME');
		expect(time).toHaveAttribute('datetime', '2026-10-29T10:15:30.000Z');
		expect(document.title).toBe('Activity · Heliophysics · Huron');
	});

	it('links collections by identifier, else by id, and namespaces within the catalog', async () => {
		await show(ENTRIES);
		const [commit, create, namespace, assign] = entries();
		expect(within(commit).getByRole('link', { name: 'collection 000000000401' })).toHaveAttribute(
			'href',
			'/collections/0192f2a4-0000-7000-8000-000000000401'
		);
		expect(
			within(create).getByRole('link', { name: 'heliophysics.fields.run001' })
		).toHaveAttribute('href', '/catalogs/heliophysics/collections/fields.run001');
		expect(within(namespace).getByRole('link', { name: 'solar-wind.ace' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/namespaces/solar-wind.ace'
		);
		expect(assign).toHaveTextContent('Assigned schema');
		expect(assign).toHaveTextContent('huron-base v1 (was huron-base v1)');
		expect(within(assign).queryByRole('link')).toBeNull();
	});

	it('keeps the raw detail in a disclosure', async () => {
		await show(ENTRIES.slice(1, 2));
		const [create] = entries();
		const details = create.querySelector('details');
		expect(details).not.toBeNull();
		expect(details?.open).toBe(false);
		const summary = within(create).getByText('Details');
		expect(summary.tagName).toBe('SUMMARY');
		expect(summary).toHaveAccessibleName(
			'Details: Created a collection, heliophysics.fields.run001, 2026-10-03 09:00 UTC'
		);
		expect(create.querySelector('pre code')?.textContent).toBe(
			'{\n  "identifier": "heliophysics.fields.run001"\n}'
		);
	});

	it('pages by the cursor alone', async () => {
		await show(ENTRIES, { nextCursor: 'older' });
		expect(screen.getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/activity?cursor=older'
		);
	});

	it('says that a page shows no entries the user may see when more pages follow', async () => {
		await show([], { nextCursor: 'older', path: '/catalogs/heliophysics/activity?cursor=newer' });
		expect(screen.getByText('No visible entries on this page.')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Next page' })).toBeInTheDocument();
		expect(screen.queryByText('No activity yet.')).toBeNull();
	});

	it('says so on an empty first page that has more after it, too', async () => {
		await show([], { nextCursor: 'older' });
		expect(screen.getByText('No visible entries on this page.')).toBeInTheDocument();
	});

	it('says when there is no activity at all', async () => {
		await show([]);
		expect(screen.getByText('No activity yet.')).toBeInTheDocument();
		expect(screen.queryByRole('navigation', { name: 'Activity pages' })).toBeNull();
	});

	it('says that a later page with nothing after it shows no visible entries, not that there are none', async () => {
		// The API decides its next cursor before it leaves out what a reader may not see.
		await show([], { path: '/catalogs/heliophysics/activity?cursor=x' });
		expect(screen.getByText('No visible entries on this page.')).toBeInTheDocument();
		expect(screen.queryByText('No activity yet.')).toBeNull();
		expect(
			within(screen.getByRole('navigation', { name: 'Activity pages' })).getByRole('link', {
				name: 'First page'
			})
		).toBeInTheDocument();
	});
});
