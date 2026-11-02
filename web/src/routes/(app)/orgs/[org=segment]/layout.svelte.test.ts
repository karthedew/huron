import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData } from '$lib/testing/catalog-data';
import { organizationFixture } from '$lib/testing/api-fixtures';
import Layout from './+layout.svelte';
vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
afterEach(() => {
	resetAppState();
	Reflect.deleteProperty(navigator, 'clipboard');
});
async function show(route = '/(app)/orgs/[org=segment]') {
	page.route = { id: route };
	render(Layout, {
		props: {
			data: {
				...catalogPageData(),
				organizationDetails: organizationFixture(),
				organizationPath: '/projects/huron/helio'
			},
			params: { org: 'helio' },
			children: createRawSnippet(() => ({ render: () => '<p>The tab</p>' }))
		}
	});
	await tick();
}
describe('Organization header', () => {
	it('shows the name and copies the complete logical path', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
		await show();
		const header = screen.getByRole('banner');
		expect(
			within(header).getByRole('heading', { level: 1, name: 'Heliophysics Division' })
		).toBeInTheDocument();
		await within(header).getByRole('button', { name: 'Copy full path' }).click();
		expect(writeText).toHaveBeenCalledWith('helio');
		expect(within(header).queryByText('Share path')).toBeNull();
		expect(screen.getByText('The tab')).toBeInTheDocument();
	});
	it('links every section and marks CLI as the current page', async () => {
		await show('/(app)/orgs/[org=segment]/cli');
		const links = within(screen.getByRole('navigation', { name: 'Organization' })).getAllByRole(
			'link'
		);
		expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
			['Catalogs2', '/orgs/helio'],
			['Access', '/orgs/helio/access'],
			['CLI', '/orgs/helio/cli']
		]);
		expect(links.filter((link) => link.getAttribute('aria-current') === 'page')).toEqual([
			links.at(-1)
		]);
	});
});
