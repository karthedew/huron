import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
import { namespaceFixture } from '$lib/testing/api-fixtures';
import { catalogPageData, catalogRole } from '$lib/testing/catalog-data';
import Page from './+page.svelte';
async function show(role: string, allowed: boolean) {
	render(Page, {
		props: {
			data: {
				...catalogPageData({ roles: [catalogRole(role)] }),
				namespace: namespaceFixture({ collections_allowed: allowed }),
				sharePath: '/projects/huron/helio/heliophysics/solar-wind',
				trail: []
			},
			params: { catalog: 'heliophysics', path: 'solar-wind' }
		}
	});
	await tick();
}
describe('namespace CLI', () => {
	it('gives contributors collection creation only in a collection namespace', async () => {
		await show('contributor', true);
		expect(
			within(screen.getByRole('region', { name: 'Create a collection here' })).getByRole('textbox')
		).toHaveValue('huron --catalog heliophysics create collection heliophysics.solar-wind.<name>');
		expect(screen.queryByRole('region', { name: 'Create a namespace here' })).toBeNull();
	});
	it('gives catalog administrators namespace creation in a structural namespace', async () => {
		await show('catalog_admin', false);
		expect(
			within(screen.getByRole('region', { name: 'Create a namespace here' })).getByRole('textbox')
		).toHaveValue(
			'huron --catalog heliophysics create namespace heliophysics.solar-wind.<name> --allow-collections'
		);
		expect(screen.queryByRole('region', { name: 'Create a collection here' })).toBeNull();
	});
	it.each([
		['reader', true],
		['contributor', false]
	] as const)('shows no mutation hints for %s in collections_allowed=%s', async (role, allowed) => {
		await show(role, allowed);
		expect(screen.queryByRole('region', { name: /Create/ })).toBeNull();
		expect(screen.getByText(/Open a collection/)).toBeInTheDocument();
	});
});
