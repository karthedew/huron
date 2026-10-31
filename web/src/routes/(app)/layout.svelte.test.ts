import { render, screen, within } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Organization } from '$api/types';
import { emptySearch } from '$lib/search';
import { catalogFixture, organizationFixture } from '$lib/testing/api-fixtures';
import { navigating, page, resetAppState } from '$lib/testing/app-state.svelte';
import { fakeUser } from '$lib/testing/events';
import Layout from './+layout.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

const navigation = vi.hoisted(() => ({ callbacks: new Array<() => void>() }));
vi.mock('$app/navigation', () => ({
	afterNavigate: (callback: () => void) => navigation.callbacks.push(callback)
}));

const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });

afterEach(() => {
	resetAppState();
	navigation.callbacks.length = 0;
	document.cookie = 'huron_org=; Max-Age=0; Path=/';
	vi.useRealTimers();
});

function show({
	organizations = [GEO, HELIO],
	unavailable = false,
	remembered = null
}: { organizations?: Organization[]; unavailable?: boolean; remembered?: string | null } = {}) {
	return render(Layout, {
		props: {
			data: {
				user: fakeUser({ name: 'Dave Diaz', subject: 'dave' }),
				organizations,
				organizationsUnavailable: unavailable,
				roles: [],
				rolesUnavailable: false,
				rememberedOrganization: remembered
			},
			params: {},
			children: createRawSnippet(() => ({ render: () => '<h1>The page</h1>' }))
		}
	});
}

/** The sidebar and the bottom navigation. */
function navigationRegions(): HTMLElement[] {
	const [, bottom] = screen.getAllByRole('navigation', { name: 'Primary' });
	return [screen.getByRole('complementary', { name: 'Sidebar' }), bottom];
}

/** What SvelteKit does after a navigation to the current `page`. */
async function navigated() {
	for (const callback of navigation.callbacks) callback();
	await tick();
}

describe('the shell', () => {
	it('skips to the page content, which comes first in main', () => {
		show();
		expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main');
		const main = screen.getByRole('main');
		expect(main).toHaveAttribute('id', 'main');
		expect(within(main).getByRole('heading', { name: 'The page' })).toBeInTheDocument();
	});

	it('has a banner with the switcher, the theme toggle and the account menu', () => {
		page.data = { organization: 'helio' };
		show();
		const banner = screen.getByRole('banner');
		expect(within(banner).getByRole('search', { name: 'Site search' })).toBeInTheDocument();
		expect(
			within(banner).getByText('Organization: Heliophysics Division, switch')
		).toBeInTheDocument();
		expect(within(banner).getByRole('button', { name: 'Use dark mode' })).toBeInTheDocument();
		expect(banner.querySelectorAll('summary')[1]).toHaveTextContent('Account: Dave Diaz');
	});

	it("leads Catalogs to the current organization's overview, else to all organizations", async () => {
		page.data = { organization: 'geo' };
		const { unmount } = show();
		for (const link of screen.getAllByRole('link', { name: 'Catalogs' })) {
			expect(link).toHaveAttribute('href', '/orgs/geo');
		}
		unmount();
		page.data = { organization: 'astro' };
		show();
		for (const link of screen.getAllByRole('link', { name: 'Catalogs' })) {
			expect(link).toHaveAttribute('href', '/orgs');
		}
		await tick();
	});

	it('marks the section of the current page in the sidebar and the bottom navigation', () => {
		page.route = { id: '/(app)/account' };
		page.url = new URL('http://localhost:4173/account');
		show();
		for (const region of navigationRegions()) {
			expect(within(region).getByRole('link', { name: 'Account' })).toHaveAttribute(
				'aria-current',
				'page'
			);
			expect(within(region).getByRole('link', { name: 'Catalogs' })).not.toHaveAttribute(
				'aria-current'
			);
		}
	});

	it('calls a link the current page only when it leads to this page', () => {
		page.data = { organization: 'geo' };
		page.route = { id: '/(app)/orgs/[org=segment]' };
		page.url = new URL('http://localhost:4173/orgs/geo?cursor=c2');
		const { unmount } = show();
		for (const region of navigationRegions()) {
			expect(within(region).getByRole('link', { name: 'Catalogs' })).toHaveAttribute(
				'aria-current',
				'page'
			);
		}
		unmount();
		page.route = { id: '/(app)/orgs' };
		page.url = new URL('http://localhost:4173/orgs');
		show();
		for (const region of navigationRegions()) {
			const catalogs = within(region).getByRole('link', { name: 'Catalogs' });
			expect(catalogs).toHaveAttribute('href', '/orgs/geo');
			expect(catalogs).toHaveAttribute('aria-current', 'true');
		}
	});

	it("counts a catalog's pages as part of the Catalogs section", () => {
		page.data = { organization: 'helio' };
		page.route = { id: '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]' };
		page.url = new URL('http://localhost:4173/catalogs/heliophysics/namespaces/fields');
		show();
		for (const region of navigationRegions()) {
			const catalogs = within(region).getByRole('link', { name: 'Catalogs' });
			expect(catalogs).toHaveAttribute('href', '/orgs/helio');
			expect(catalogs).toHaveAttribute('aria-current', 'true');
		}
	});

	it("counts a catalog's search as searching, not as part of the Catalogs section", () => {
		page.data = { organization: 'helio', catalog: catalogFixture() };
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)/search' };
		page.url = new URL('http://localhost:4173/catalogs/heliophysics/search?q=wind');
		show();
		for (const region of navigationRegions()) {
			const catalogs = within(region).getByRole('link', { name: 'Catalogs' });
			expect(catalogs).toHaveAttribute('href', '/orgs/helio');
			expect(catalogs).not.toHaveAttribute('aria-current');
			expect(within(region).getByRole('link', { name: 'Search' })).toHaveAttribute(
				'aria-current',
				'page'
			);
		}
	});

	it("counts an organization's search as searching, not as part of the Catalogs section", () => {
		page.data = { organization: 'helio' };
		page.route = { id: '/(app)/orgs/[org=segment]/search' };
		page.url = new URL('http://localhost:4173/orgs/helio/search?q=wind');
		show();
		for (const region of navigationRegions()) {
			expect(within(region).getByRole('link', { name: 'Catalogs' })).not.toHaveAttribute(
				'aria-current'
			);
			const search = within(region).getByRole('link', { name: 'Search' });
			expect(search).toHaveAttribute('href', '/orgs/helio/search');
			expect(search).toHaveAttribute('aria-current', 'page');
		}
	});

	it('marks Search as the section of the page that asks which organization to search', () => {
		page.data = { organization: 'geo' };
		page.route = { id: '/(app)/search' };
		page.url = new URL('http://localhost:4173/search?q=wind');
		show();
		for (const region of navigationRegions()) {
			const search = within(region).getByRole('link', { name: 'Search' });
			// It leads to the remembered organization's search, which this page is not.
			expect(search).toHaveAttribute('href', '/orgs/geo/search');
			expect(search).toHaveAttribute('aria-current', 'true');
			expect(within(region).getByRole('link', { name: 'Catalogs' })).not.toHaveAttribute(
				'aria-current'
			);
		}
	});

	it('leads Search to what the page belongs to: its catalog, else its organization, else ask', () => {
		page.data = { organization: 'helio', catalog: catalogFixture() };
		page.route = { id: '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]' };
		page.url = new URL('http://localhost:4173/catalogs/heliophysics/namespaces/fields');
		const { unmount } = show();
		const hrefs = () =>
			navigationRegions().map((region) =>
				within(region).getByRole('link', { name: 'Search' }).getAttribute('href')
			);
		expect(hrefs()).toEqual(['/catalogs/heliophysics/search', '/catalogs/heliophysics/search']);
		for (const region of navigationRegions()) {
			expect(within(region).getByRole('link', { name: 'Search' })).not.toHaveAttribute(
				'aria-current'
			);
		}
		unmount();
		page.data = { organization: 'geo' };
		page.route = { id: '/(app)/orgs/[org=segment]' };
		page.url = new URL('http://localhost:4173/orgs/geo');
		const second = show();
		expect(hrefs()).toEqual(['/orgs/geo/search', '/orgs/geo/search']);
		second.unmount();
		page.data = { organization: null };
		page.route = { id: '/(app)/account' };
		page.url = new URL('http://localhost:4173/account');
		show();
		expect(hrefs()).toEqual(['/search', '/search']);
	});

	it('has a search box in the banner that searches what the page belongs to', () => {
		page.data = { organization: 'helio', catalog: catalogFixture() };
		page.route = { id: '/(app)/catalogs/[catalog=segment]/(overview)' };
		page.url = new URL('http://localhost:4173/catalogs/heliophysics');
		const { unmount } = show();
		const banner = screen.getByRole('banner');
		const box = within(banner).getByRole('search', { name: 'Site search' });
		expect(box).toHaveAttribute('action', '/catalogs/heliophysics/search');
		expect(within(box).getByRole('searchbox', { name: 'Search Heliophysics' })).toHaveValue('');
		unmount();
		page.data = { organization: 'helio' };
		page.route = { id: '/(app)/orgs/[org=segment]' };
		page.url = new URL('http://localhost:4173/orgs/helio');
		const second = show();
		expect(screen.getByRole('search', { name: 'Site search' })).toHaveAttribute(
			'action',
			'/orgs/helio/search'
		);
		expect(
			screen.getByRole('searchbox', { name: 'Search Heliophysics Division' })
		).toBeInTheDocument();
		second.unmount();
		page.data = { organization: null };
		page.route = { id: '/(app)/account' };
		page.url = new URL('http://localhost:4173/account');
		show();
		expect(screen.getByRole('search', { name: 'Site search' })).toHaveAttribute(
			'action',
			'/search'
		);
		expect(screen.getByRole('searchbox', { name: 'Search' })).toBeInTheDocument();
	});

	it('holds the text of the search a search page shows, and of no other page', async () => {
		page.data = { organization: 'helio', search: { ...emptySearch(), q: 'solar wind' } };
		page.route = { id: '/(app)/orgs/[org=segment]/search' };
		page.url = new URL('http://localhost:4173/orgs/helio/search?q=solar+wind');
		show();
		expect(screen.getByRole('searchbox', { name: 'Search Heliophysics Division' })).toHaveValue(
			'solar wind'
		);
		// Typed and not sent: another page shows its own text, not what was typed.
		const field = screen.getByRole('searchbox', { name: 'Search Heliophysics Division' });
		if (!(field instanceof HTMLInputElement)) throw new Error('no field');
		field.value = 'typed';
		page.data = { organization: 'helio' };
		page.route = { id: '/(app)/orgs/[org=segment]' };
		page.url = new URL('http://localhost:4173/orgs/helio');
		await tick();
		expect(screen.getByRole('searchbox', { name: 'Search Heliophysics Division' })).toHaveValue('');
	});

	it('keeps what was typed in the box while the page stays, as when skipping to the content', async () => {
		page.data = { organization: 'helio', search: { ...emptySearch(), q: 'mag' } };
		page.route = { id: '/(app)/orgs/[org=segment]/search' };
		page.url = new URL('http://localhost:4173/orgs/helio/search?q=mag');
		show();
		const field = screen.getByRole('searchbox', { name: 'Search Heliophysics Division' });
		if (!(field instanceof HTMLInputElement)) throw new Error('no field');
		field.value = 'typed';
		// The skip link leads to #main: the address changes, the page does not.
		page.url = new URL('http://localhost:4173/orgs/helio/search?q=mag#main');
		await tick();
		expect(screen.getByRole('searchbox', { name: 'Search Heliophysics Division' })).toBe(field);
		expect(field).toHaveValue('typed');
	});

	it('notes that the website is read-only', () => {
		show();
		const sidebar = screen.getByRole('complementary', { name: 'Sidebar' });
		expect(
			within(sidebar).getByText(/Read-only · changes are made with the huron CLI/)
		).toBeInTheDocument();
	});

	it('remembers a visible organization after a navigation', async () => {
		page.data = { organization: 'geo' };
		show();
		await navigated();
		expect(document.cookie).toBe('huron_org=geo');
	});

	it('shows the remembered organization on an error page, which names none', () => {
		page.data = {};
		show({ remembered: 'geo' });
		expect(screen.getByText('Organization: Earth Science, switch')).toBeInTheDocument();
		for (const link of screen.getAllByRole('link', { name: 'Catalogs' })) {
			expect(link).toHaveAttribute('href', '/orgs/geo');
		}
	});

	it('keeps the organization it last remembered for a later error page', async () => {
		page.data = { organization: 'helio' };
		show({ remembered: 'geo' });
		await navigated();
		page.data = {};
		await tick();
		expect(screen.getByText('Organization: Heliophysics Division, switch')).toBeInTheDocument();
	});

	it('shows no remembered organization the user cannot see', () => {
		page.data = {};
		show({ remembered: 'astro' });
		expect(screen.getByText('Choose organization')).toBeInTheDocument();
	});

	it('remembers nothing for a page without a visible organization', async () => {
		page.data = { organization: 'astro' };
		show();
		await navigated();
		page.data = {};
		await navigated();
		expect(document.cookie).toBe('');
	});

	it('shows the loading bar and says so only once a navigation is slow', async () => {
		vi.useFakeTimers();
		show();
		const status = screen
			.getAllByRole('status')
			.find((element) => element.closest('main') === null);
		if (status === undefined) throw new Error('no loading status');
		navigating.to = {
			params: {},
			route: { id: '/(app)/orgs' },
			url: new URL('http://localhost:4173/orgs'),
			scroll: null
		};
		await tick();
		expect(screen.getByRole('main')).toHaveAttribute('aria-busy', 'true');
		expect(status.textContent).toBe('');
		await vi.advanceTimersByTimeAsync(199);
		expect(status.textContent).toBe('');
		await vi.advanceTimersByTimeAsync(1);
		expect(status).toHaveTextContent('Loading…');
		expect(document.querySelector('.animate-loading')).not.toBeNull();

		navigating.to = null;
		await tick();
		expect(status.textContent).toBe('');
		expect(screen.getByRole('main')).not.toHaveAttribute('aria-busy');
		expect(document.querySelector('.animate-loading')).toBeNull();
	});

	it('keeps the shell when the organizations are unavailable', () => {
		show({ organizations: [], unavailable: true });
		const banner = screen.getByRole('banner');
		expect(within(banner).getByText('Organizations unavailable')).toBeInTheDocument();
		expect(within(banner).getByRole('link', { name: 'Try again' })).toBeInTheDocument();
	});
});
