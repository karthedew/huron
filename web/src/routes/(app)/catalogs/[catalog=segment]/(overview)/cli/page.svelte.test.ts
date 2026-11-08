import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
import { catalogPageData, catalogRole } from '$lib/testing/catalog-data';
import Page from './+page.svelte';
async function show(role: string) {
	render(Page, {
		props: {
			data: catalogPageData({ roles: [catalogRole(role)] }),
			params: { catalog: 'heliophysics' }
		}
	});
	await tick();
}
describe('catalog CLI', () => {
	it('gives readers search without administrative commands', async () => {
		await show('reader');
		expect(
			within(screen.getByRole('region', { name: 'Search this catalog' })).getByRole('textbox')
		).toHaveValue('huron --catalog heliophysics search');
		expect(screen.queryByRole('region', { name: 'Create a namespace here' })).toBeNull();
		expect(screen.queryByRole('region', { name: 'Grant a role' })).toBeNull();
	});
	it('gives administrators namespace creation and the grant command', async () => {
		await show('catalog_admin');
		expect(
			within(screen.getByRole('region', { name: 'Create a namespace here' })).getByRole('textbox')
		).toHaveValue(
			'huron --catalog heliophysics create namespace heliophysics.<name> --allow-collections'
		);
		expect(
			within(screen.getByRole('region', { name: 'Grant a role' })).getByRole('textbox')
		).toHaveValue('huron --catalog heliophysics adm grant <role> <ldap-group>');
	});
});
