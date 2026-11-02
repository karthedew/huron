import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Breadcrumbs from './Breadcrumbs.svelte';

describe('Breadcrumbs', () => {
	it('lists the way to the page in order and marks the page itself', () => {
		render(Breadcrumbs, {
			props: {
				crumbs: [
					{ label: 'Heliophysics Division', href: '/orgs/helio' },
					{ label: 'Heliophysics', href: '/catalogs/heliophysics' },
					{ label: 'ace', href: '/catalogs/heliophysics/namespaces/ace', current: true }
				]
			}
		});
		const trail = screen.getByRole('navigation', { name: 'Breadcrumb' });
		const items = within(within(trail).getByRole('list')).getAllByRole('listitem');
		expect(items.map((item) => item.textContent?.trim())).toEqual([
			'Heliophysics Division',
			'Heliophysics',
			'ace'
		]);
		const links = within(trail).getAllByRole('link');
		expect(links.map((link) => link.getAttribute('aria-current'))).toEqual([null, null, 'page']);
		expect(links[1]).toHaveAttribute('href', '/catalogs/heliophysics');
		// The separators are drawn, not read.
		expect(trail.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(2);
	});
});
