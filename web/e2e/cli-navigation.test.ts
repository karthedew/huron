import { expect } from '@playwright/test';
import { signIn, test } from './support/harness.ts';

test('compact object headers copy complete identifiers and link to their CLI pages', async ({
	page,
	context
}) => {
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);
	await page.setViewportSize({ width: 1440, height: 900 });
	await signIn(page, 'alice');
	const objects = [
		{ path: '/orgs/helio', identifier: 'helio', section: 'Organization' },
		{ path: '/catalogs/heliophysics', identifier: 'heliophysics', section: 'Catalog' },
		{
			path: '/catalogs/heliophysics/namespaces/solar-wind.ace',
			identifier: 'heliophysics.solar-wind.ace',
			section: 'Namespace'
		},
		{
			path: '/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024',
			identifier: 'heliophysics.solar-wind.ace.mag-l2-2024',
			section: 'Collection'
		}
	];
	for (const object of objects) {
		await page.goto(object.path);
		const main = page.getByRole('main');
		await main.getByRole('button', { name: 'Copy full path' }).click();
		expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(object.identifier);
		await main
			.getByRole('navigation', { name: object.section, exact: true })
			.getByRole('link', { name: 'CLI', exact: true })
			.click();
		await expect(page).toHaveURL(new RegExp(`${object.path}/cli$`));
		await expect(main.getByRole('heading', { name: 'With the CLI' })).toBeVisible();
		await expect(
			main
				.getByRole('navigation', { name: object.section, exact: true })
				.getByRole('link', { name: 'CLI', exact: true })
		).toHaveAttribute('aria-current', 'page');
		if (object.section !== 'Organization')
			await expect(
				main.getByRole('navigation', { name: 'Breadcrumb', includeHidden: true })
			).toBeHidden();
		if (object.section === 'Namespace')
			await expect(
				page
					.getByRole('navigation', { name: 'Explorer' })
					.getByRole('link', { name: 'ace', exact: true })
			).toHaveAttribute('aria-current', 'true');
	}
	await page.setViewportSize({ width: 816, height: 900 });
	await page.goto('/catalogs/heliophysics/namespaces/solar-wind.ace/cli');
	await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toBeVisible();
	await expect(
		page
			.getByRole('navigation', { name: 'Breadcrumb' })
			.getByRole('link', { name: 'ace', exact: true })
	).not.toHaveAttribute('aria-current');
	await expect(
		page.getByRole('navigation', { name: 'Explorer', includeHidden: true })
	).toBeHidden();
});
