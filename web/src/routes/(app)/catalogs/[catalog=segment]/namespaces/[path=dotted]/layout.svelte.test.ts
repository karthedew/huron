import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { page, resetAppState } from '$lib/testing/app-state.svelte';
import { catalogPageData } from '$lib/testing/catalog-data';
import { namespaceFixture } from '$lib/testing/api-fixtures';
import Layout from './+layout.svelte';
vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));
afterEach(() => {
	resetAppState();
	Reflect.deleteProperty(navigator, 'clipboard');
});
async function show(route = '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]') {
	page.route = { id: route };
	render(Layout, {
		props: {
			data: {
				...catalogPageData(),
				namespace: namespaceFixture(),
				sharePath: '/projects/huron/helio/heliophysics/solar-wind',
				trail: []
			},
			params: { catalog: 'heliophysics', path: 'solar-wind' },
			children: createRawSnippet(() => ({ render: () => '<p>The tab</p>' }))
		}
	});
	await tick();
}
describe('Namespace header', () => {
	it('shows the name and copies the complete logical path', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
		await show();
		const header = screen.getByRole('banner');
		expect(
			within(header).getByRole('heading', { level: 1, name: 'solar-wind' })
		).toBeInTheDocument();
		await within(header).getByRole('button', { name: 'Copy full path' }).click();
		expect(writeText).toHaveBeenCalledWith('heliophysics.solar-wind');
		expect(within(header).queryByText('Share path')).toBeNull();
		expect(screen.getByText('The tab')).toBeInTheDocument();
	});
	it('links every section and marks CLI as the current page', async () => {
		await show('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]/cli');
		const links = within(screen.getByRole('navigation', { name: 'Namespace' })).getAllByRole(
			'link'
		);
		expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
			['Overview', '/catalogs/heliophysics/namespaces/solar-wind'],
			['CLI', '/catalogs/heliophysics/namespaces/solar-wind/cli']
		]);
		expect(links.filter((link) => link.getAttribute('aria-current') === 'page')).toEqual([
			links.at(-1)
		]);
	});
});
