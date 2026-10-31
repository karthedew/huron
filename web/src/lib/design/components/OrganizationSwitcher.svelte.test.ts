import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Organization } from '$api/types';
import { organizationFixture } from '$lib/testing/api-fixtures';
import OrganizationSwitcher from './OrganizationSwitcher.svelte';

const state = vi.hoisted(() => {
	const route: { id: string | null } = { id: '/(app)' };
	return { page: { route, url: new URL('http://localhost:4173/') } };
});
vi.mock('$app/state', () => state);

const navigation = vi.hoisted(() => ({ callbacks: new Array<() => void>() }));
vi.mock('$app/navigation', () => ({
	afterNavigate: (callback: () => void) => navigation.callbacks.push(callback)
}));

const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });
const ASTRO = organizationFixture({ id: 'o-astro', name: 'astro', display_name: '' });

afterEach(() => {
	state.page.route.id = '/(app)';
	state.page.url = new URL('http://localhost:4173/');
	navigation.callbacks.length = 0;
});

function show(
	organizations: Organization[] = [ASTRO, GEO, HELIO],
	current: Organization | null = HELIO,
	unavailable = false
) {
	return render(OrganizationSwitcher, { props: { organizations, current, unavailable } });
}

function menu(): { details: HTMLDetailsElement; summary: HTMLElement } {
	const details = document.querySelector('details');
	const summary = details?.querySelector('summary');
	if (!details || !(summary instanceof HTMLElement)) throw new Error('no switcher menu');
	return { details, summary };
}

/** Open the menu by its summary; the browser reports the change with a later `toggle` event. */
async function open() {
	const { details, summary } = menu();
	const toggled = new Promise((resolve) =>
		details.addEventListener('toggle', resolve, { once: true })
	);
	await fireEvent.click(summary);
	await toggled;
	await tick();
	expect(details.open).toBe(true);
	return menu();
}

describe('OrganizationSwitcher', () => {
	it('names the current organization and lists every visible one', async () => {
		show();
		const { summary } = menu();
		expect(within(summary).getByText('Organization: Heliophysics Division, switch')).toHaveClass(
			'sr-only'
		);
		expect(within(summary).getByText('Heliophysics Division')).toHaveAttribute(
			'aria-hidden',
			'true'
		);
		await open();
		const list = screen.getByRole('list', { name: 'Organizations' });
		const links = within(list).getAllByRole('link');
		expect(links.map((link) => link.textContent?.trim())).toEqual([
			'astro',
			'Earth Science geo',
			'Heliophysics Division helio'
		]);
		expect(links.map((link) => link.getAttribute('href'))).toEqual([
			'/orgs/astro',
			'/orgs/geo',
			'/orgs/helio'
		]);
		expect(links[2]).toHaveAttribute('aria-current', 'true');
		expect(links[2].querySelector('svg')).toHaveClass('lucide-check');
		expect(links[1]).not.toHaveAttribute('aria-current');
		expect(screen.getByRole('link', { name: 'All organizations' })).toHaveAttribute(
			'href',
			'/orgs'
		);
	});

	it('asks to choose an organization when the page has none', () => {
		show([GEO, HELIO], null);
		expect(menu().summary).toHaveTextContent('Choose organization');
	});

	it('keeps an organization sub-route and its query, without cursors and notices', async () => {
		state.page.route.id = '/(app)/orgs/[org=segment]/search';
		state.page.url = new URL(
			'http://localhost:4173/orgs/helio/search?q=wind&cursor=abc&notice=page_expired&label=a%3Db'
		);
		show();
		await open();
		expect(screen.getByRole('link', { name: 'Earth Science geo' })).toHaveAttribute(
			'href',
			'/orgs/geo/search?q=wind&label=a%3Db'
		);
	});

	it('keeps of the address only what the search reads, in its own order', async () => {
		state.page.route.id = '/(app)/orgs/[org=segment]/search';
		state.page.url = new URL(
			`http://localhost:4173/orgs/helio/search?junk=${'Z'.repeat(15_000)}&label=a:b&q=%20wind%20&state=draft`
		);
		show();
		await open();
		expect(screen.getByRole('link', { name: 'Earth Science geo' })).toHaveAttribute(
			'href',
			'/orgs/geo/search?q=wind&label=a%3Db&state=draft'
		);
	});

	it('repeats no more of a long search than one link of many may hold', async () => {
		// One link per organization: a platform admin may see 500.
		const many = Array.from({ length: 500 }, (_, index) =>
			organizationFixture({ id: `o-${index}`, name: `org-${index}`, display_name: '' })
		);
		const label = `k=${'𝕏'.repeat(100)}`;
		state.page.route.id = '/(app)/orgs/[org=segment]/search';
		state.page.url = new URL(
			`http://localhost:4173/orgs/org-0/search?${new URLSearchParams([
				['q', 'wind'],
				...Array.from({ length: 6 }, (_, index): [string, string] => ['label', `${index}${label}`])
			])}`
		);
		show(many, many[0]);
		await open();
		const hrefs = within(screen.getByRole('list', { name: 'Organizations' }))
			.getAllByRole('link')
			.map((link) => link.getAttribute('href') ?? '');
		expect(hrefs[1]).toBe('/orgs/org-1/search?q=wind');
		expect(hrefs.every((href) => href.length <= '/orgs/org-499/search'.length + 1024)).toBe(true);
	});

	it("goes to the other organization's overview from its catalogs list, without its query", async () => {
		state.page.route.id = '/(app)/orgs/[org=segment]';
		state.page.url = new URL(
			`http://localhost:4173/orgs/helio?cursor=abc&notice=page_expired&junk=${'Z'.repeat(15_000)}`
		);
		show();
		await open();
		expect(screen.getByRole('link', { name: 'Earth Science geo' })).toHaveAttribute(
			'href',
			'/orgs/geo'
		);
	});

	it("goes to an organization's overview from pages outside organizations", async () => {
		state.page.route.id = '/(app)/account';
		state.page.url = new URL('http://localhost:4173/account?tab=x');
		show();
		await open();
		expect(screen.getByRole('link', { name: 'Earth Science geo' })).toHaveAttribute(
			'href',
			'/orgs/geo'
		);
	});

	it('shows a single organization as a label with the link to all', () => {
		show([HELIO], HELIO);
		expect(document.querySelector('details')).toBeNull();
		expect(screen.getByText('Organization: Heliophysics Division')).toHaveClass('sr-only');
		expect(screen.getByText('Heliophysics Division')).toHaveAttribute('aria-hidden', 'true');
		expect(screen.getByRole('link', { name: 'All organizations' })).toHaveAttribute(
			'href',
			'/orgs'
		);
	});

	it('says when there are no organizations, with nothing to choose from', () => {
		show([], null);
		expect(screen.getByText('No organizations')).toBeInTheDocument();
		expect(document.querySelector('details')).toBeNull();
		expect(screen.queryByRole('link')).not.toBeInTheDocument();
	});

	it('offers to try again when the organizations could not be loaded', () => {
		state.page.url = new URL('http://localhost:4173/orgs/helio?x=1');
		show([], null, true);
		expect(screen.getByText('Organizations unavailable')).toBeInTheDocument();
		const retry = screen.getByRole('link', { name: 'Try again' });
		expect(retry).toHaveAttribute('href', '/orgs/helio?x=1');
		expect(retry).toHaveAttribute('data-sveltekit-reload');
		expect(document.querySelector('details')).toBeNull();
	});

	it('closes on Escape and gives focus back to its summary', async () => {
		show();
		const { details, summary } = await open();
		screen.getByRole('link', { name: 'Earth Science geo' }).focus();
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(details.open).toBe(false);
		expect(document.activeElement).toBe(summary);
	});

	it('moves through its links with the arrow keys, Home and End', async () => {
		show();
		const { summary } = await open();
		summary.focus();
		const links = [...menu().details.querySelectorAll('a')];
		const press = async (key: string) => {
			await fireEvent.keyDown(document.activeElement ?? window, { key });
			return document.activeElement;
		};
		expect(await press('ArrowDown')).toBe(links[0]);
		expect(await press('ArrowDown')).toBe(links[1]);
		expect(await press('ArrowUp')).toBe(links[0]);
		expect(await press('ArrowUp')).toBe(links[3]);
		expect(await press('ArrowDown')).toBe(links[0]);
		expect(await press('End')).toBe(links[3]);
		expect(await press('Home')).toBe(links[0]);
		expect(links[3]).toHaveTextContent('All organizations');
	});

	it('acts on a menu opened a moment ago, before the browser reports the toggle', async () => {
		show();
		const { details, summary } = menu();
		summary.click();
		expect(details.open).toBe(true);
		summary.focus();
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
		expect(document.activeElement).toBe(details.querySelector('a'));
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
		expect(details.open).toBe(false);
		expect(document.activeElement).toBe(summary);
		await new Promise((resolve) => setTimeout(resolve, 0));
		await tick();
		expect(details.open).toBe(false);
	});

	it('leaves the arrow keys alone while closed', async () => {
		show();
		const { summary } = menu();
		summary.focus();
		await fireEvent.keyDown(summary, { key: 'ArrowDown' });
		expect(document.activeElement).toBe(summary);
	});

	it('closes on a click outside, and stays open for a click inside', async () => {
		show();
		const { details } = await open();
		await fireEvent.click(screen.getByRole('list', { name: 'Organizations' }));
		expect(details.open).toBe(true);
		await fireEvent.click(document.body);
		expect(details.open).toBe(false);
	});

	it('closes when focus moves elsewhere', async () => {
		const outside = document.createElement('button');
		document.body.append(outside);
		show();
		const { details } = await open();
		const link = screen.getByRole('link', { name: 'Earth Science geo' });
		link.focus();
		await fireEvent.focusOut(link, { relatedTarget: outside });
		expect(details.open).toBe(false);
		outside.remove();
	});

	it('stays open when focus leaves for no element, as a click on its own text makes it', async () => {
		show();
		const { details } = await open();
		const link = screen.getByRole('link', { name: 'Earth Science geo' });
		link.focus();
		await fireEvent.focusOut(link, { relatedTarget: null });
		expect(details.open).toBe(true);
	});

	it('leaves the arrow keys to the page while focus is outside the open menu', async () => {
		show();
		await open();
		const focused = document.activeElement;
		if (focused instanceof HTMLElement) focused.blur();
		expect(document.activeElement).toBe(document.body);
		await fireEvent.keyDown(window, { key: 'ArrowDown' });
		expect(document.activeElement).toBe(document.body);
		await fireEvent.keyDown(window, { key: 'End' });
		expect(document.activeElement).toBe(document.body);
	});

	it('closes after a navigation', async () => {
		show();
		const { details } = await open();
		for (const callback of navigation.callbacks) callback();
		await tick();
		expect(details.open).toBe(false);
	});
});
