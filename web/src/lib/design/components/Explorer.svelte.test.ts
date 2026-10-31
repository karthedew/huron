import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ExplorerCurrent, ExplorerLevel, TrailLevel } from '$lib/explorer';
import { fakeFetch, jsonResponse, type FetchAnswer } from '$lib/testing/api-fixtures';
import Explorer from './Explorer.svelte';

const navigation = vi.hoisted(() => ({ callbacks: new Array<() => void>() }));
vi.mock('$app/navigation', () => ({
	afterNavigate: (callback: () => void) => navigation.callbacks.push(callback)
}));
const session = vi.hoisted(() => ({ signInAgain: vi.fn() }));
vi.mock('$lib/sign-in-again', () => session);

afterEach(() => {
	navigation.callbacks.length = 0;
	session.signInAgain.mockReset();
	vi.unstubAllGlobals();
});

const ROOT: ExplorerLevel = {
	parent: '',
	namespaces: [
		{ name: 'deep', path: 'deep', empty: false },
		{ name: 'empty', path: 'empty', empty: true },
		{ name: 'solar-wind', path: 'solar-wind', empty: false }
	],
	namespacesNext: null,
	collections: [],
	collectionsNext: null
};

const SOLAR_WIND: ExplorerLevel = {
	parent: 'solar-wind',
	namespaces: [
		{ name: 'ace', path: 'solar-wind.ace', empty: false },
		{ name: 'wind', path: 'solar-wind.wind', empty: false }
	],
	namespacesNext: null,
	collections: [],
	collectionsNext: null
};

const ACE: ExplorerLevel = {
	parent: 'solar-wind.ace',
	namespaces: [],
	namespacesNext: null,
	collections: [
		{ name: 'mag-l2-2024', identifier: 'heliophysics.solar-wind.ace.mag-l2-2024' },
		{ name: 'swepam-2024', identifier: 'heliophysics.solar-wind.ace.swepam-2024' }
	],
	collectionsNext: 'c2'
};

const WIND: ExplorerLevel = {
	parent: 'solar-wind.wind',
	namespaces: [],
	namespacesNext: null,
	collections: [{ name: 'mfi-2023', identifier: 'heliophysics.solar-wind.wind.mfi-2023' }],
	collectionsNext: null
};

const DEEP: ExplorerLevel = {
	parent: 'deep',
	namespaces: [{ name: 'a', path: 'deep.a', empty: false }],
	namespacesNext: null,
	collections: [],
	collectionsNext: null
};

const CATALOGS = [
	{ name: 'heliophysics', display_name: 'Heliophysics' },
	{ name: 'space-weather', display_name: 'Space Weather' }
];

interface ShowOptions {
	levels?: TrailLevel[];
	current?: ExplorerCurrent;
	catalogs?: { name: string; display_name: string }[];
	moreCatalogs?: boolean;
}

async function show({
	levels = [ROOT],
	current = { kind: 'catalog', overview: true },
	catalogs = CATALOGS,
	moreCatalogs = false
}: ShowOptions = {}) {
	const shown = render(Explorer, {
		props: {
			organization: 'helio',
			catalogs,
			moreCatalogs,
			catalog: { name: 'heliophysics', display_name: 'Heliophysics' },
			levels,
			current
		}
	});
	await tick();
	return shown;
}

function stubFetch(...answers: FetchAnswer[]) {
	const fake = fakeFetch(...answers);
	vi.stubGlobal('fetch', fake.fetch);
	return fake.calls;
}

function explorer() {
	return screen.getByRole('navigation', { name: 'Explorer' });
}

function toggleOf(name: string) {
	return within(explorer()).getByRole('button', { name: `Contents of ${name}` });
}

/** The explorer's one live region: what it says about loading folders. */
function liveRegion() {
	return within(explorer()).getByRole('status');
}

/** What SvelteKit does once a navigation has rendered the next page. */
async function navigated() {
	for (const callback of navigation.callbacks) callback();
	await tick();
}

describe('Explorer', () => {
	it("lists the organization's catalogs and opens the current one", async () => {
		await show();
		const tree = explorer();
		const catalog = within(tree).getByRole('link', { name: 'Heliophysics' });
		expect(catalog).toHaveAttribute('href', '/catalogs/heliophysics');
		expect(catalog).toHaveAttribute('aria-current', 'page');
		expect(within(tree).getByRole('link', { name: 'Space Weather' })).toHaveAttribute(
			'href',
			'/catalogs/space-weather'
		);
		expect(within(tree).getByRole('link', { name: 'solar-wind' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/namespaces/solar-wind'
		);
		expect(toggleOf('Heliophysics')).toHaveAttribute('aria-expanded', 'true');
	});

	it('offers no toggle for a namespace with nothing in it', async () => {
		await show();
		expect(within(explorer()).queryByRole('button', { name: 'Contents of empty' })).toBeNull();
		expect(toggleOf('deep')).toHaveAttribute('aria-expanded', 'false');
	});

	it('fetches a folder from the tree endpoint and keeps focus on its toggle', async () => {
		let release = () => {};
		const held = new Promise<void>((resolve) => (release = resolve));
		const calls = stubFetch(async () => {
			await held;
			return jsonResponse(SOLAR_WIND);
		});
		await show();
		expect(liveRegion().textContent).toBe('');
		const toggle = toggleOf('solar-wind');
		toggle.focus();
		await fireEvent.click(toggle);
		expect(toggle).toHaveAttribute('aria-expanded', 'true');
		const folder = toggle.closest('li');
		expect(folder).toHaveAttribute('aria-busy', 'true');
		expect(within(folder ?? document.body).getByText('Loading…')).toBeInTheDocument();
		// Outside the busy folder, so screen readers hear it while the folder loads.
		expect(folder?.contains(liveRegion())).toBe(false);
		expect(liveRegion()).toHaveTextContent('Loading solar-wind…');
		expect(calls).toHaveLength(1);
		expect(calls[0].url).toBe('/catalogs/heliophysics/tree?parent=solar-wind');
		expect(calls[0].init?.headers).toEqual({
			accept: 'application/json',
			'x-huron-fetch': '1'
		});

		release();
		const ace = await within(explorer()).findByRole('link', { name: 'ace' });
		expect(ace).toHaveAttribute('href', '/catalogs/heliophysics/namespaces/solar-wind.ace');
		expect(folder).not.toHaveAttribute('aria-busy');
		expect(screen.queryByText('Loading…')).toBeNull();
		expect(liveRegion()).toHaveTextContent('Loaded solar-wind.');
		expect(document.activeElement).toBe(toggle);
	});

	it('closes and reopens a folder without fetching it again', async () => {
		const calls = stubFetch(jsonResponse(SOLAR_WIND));
		await show();
		const toggle = toggleOf('solar-wind');
		await fireEvent.click(toggle);
		await within(explorer()).findByRole('link', { name: 'ace' });
		await fireEvent.click(toggle);
		expect(toggle).toHaveAttribute('aria-expanded', 'false');
		expect(within(explorer()).queryByRole('link', { name: 'ace' })).toBeNull();
		await fireEvent.click(toggle);
		expect(within(explorer()).getByRole('link', { name: 'ace' })).toBeInTheDocument();
		expect(calls).toHaveLength(1);
	});

	it('fetches a folder closed and opened again while it loads only once', async () => {
		// A second answer could otherwise settle the folder on the wrong one.
		const calls = stubFetch(() => new Promise<Response>(() => {}));
		await show();
		const toggle = toggleOf('solar-wind');
		await fireEvent.click(toggle);
		await fireEvent.click(toggle);
		await fireEvent.click(toggle);
		expect(toggle).toHaveAttribute('aria-expanded', 'true');
		expect(calls).toHaveLength(1);
	});

	it('closes and opens the catalog itself', async () => {
		await show();
		const toggle = toggleOf('Heliophysics');
		await fireEvent.click(toggle);
		expect(toggle).toHaveAttribute('aria-expanded', 'false');
		expect(within(explorer()).queryByRole('link', { name: 'deep' })).toBeNull();
		await fireEvent.click(toggle);
		expect(within(explorer()).getByRole('link', { name: 'deep' })).toBeInTheDocument();
	});

	it('sends the user to sign in again when the session ended', async () => {
		stubFetch(jsonResponse({ code: 'UNAUTHENTICATED' }, 401));
		await show();
		await fireEvent.click(toggleOf('solar-wind'));
		await waitFor(() => expect(session.signInAgain).toHaveBeenCalledOnce());
	});

	it('says when a folder could not load and retries with focus on its toggle', async () => {
		const calls = stubFetch(jsonResponse({ code: 'UNAVAILABLE' }, 503), jsonResponse(SOLAR_WIND));
		await show();
		const toggle = toggleOf('solar-wind');
		await fireEvent.click(toggle);
		const retry = await within(explorer()).findByRole('button', {
			name: 'Retry loading solar-wind'
		});
		expect(retry).toHaveTextContent('Retry');
		expect(retry.closest('p')).toHaveTextContent("Couldn't load · Retry");
		expect(liveRegion()).toHaveTextContent("Couldn't load solar-wind.");
		retry.focus();
		await fireEvent.click(retry);
		expect(document.activeElement).toBe(toggle);
		expect(liveRegion()).toHaveTextContent('Loading solar-wind…');
		expect(await within(explorer()).findByRole('link', { name: 'wind' })).toBeInTheDocument();
		expect(screen.queryByText("Couldn't load ·")).toBeNull();
		expect(liveRegion()).toHaveTextContent('Loaded solar-wind.');
		expect(calls).toHaveLength(2);
	});

	it("closes a folder reopened over the page's contents once the next page lacks them", async () => {
		const calls = stubFetch(jsonResponse(ACE));
		const shown = await show({
			levels: [ROOT, SOLAR_WIND, ACE],
			current: { kind: 'namespace', path: 'solar-wind.ace' }
		});
		await fireEvent.click(toggleOf('ace'));
		await fireEvent.click(toggleOf('ace'));
		expect(toggleOf('ace')).toHaveAttribute('aria-expanded', 'true');
		expect(within(explorer()).getByRole('link', { name: 'mag-l2-2024' })).toBeInTheDocument();
		expect(calls).toHaveLength(0);

		shown.rerender({
			levels: [ROOT, SOLAR_WIND, WIND],
			current: { kind: 'namespace', path: 'solar-wind.wind' }
		});
		await navigated();
		// Never open and empty: closed, with nothing on its way.
		expect(toggleOf('ace')).toHaveAttribute('aria-expanded', 'false');
		expect(toggleOf('ace').closest('li')).not.toHaveAttribute('aria-busy');
		expect(within(explorer()).queryByRole('link', { name: 'mag-l2-2024' })).toBeNull();
		expect(within(explorer()).getByRole('link', { name: 'mfi-2023' })).toBeInTheDocument();
		expect(calls).toHaveLength(0);

		await fireEvent.click(toggleOf('ace'));
		expect(toggleOf('ace')).toHaveAttribute('aria-expanded', 'true');
		expect(
			await within(explorer()).findByRole('link', { name: 'mag-l2-2024' })
		).toBeInTheDocument();
		expect(calls.map(({ url }) => url)).toEqual([
			'/catalogs/heliophysics/tree?parent=solar-wind.ace'
		]);
	});

	it('keeps a folder whose contents it fetched open on the next page', async () => {
		const calls = stubFetch(jsonResponse(SOLAR_WIND));
		const shown = await show();
		await fireEvent.click(toggleOf('solar-wind'));
		await within(explorer()).findByRole('link', { name: 'ace' });

		shown.rerender({ levels: [ROOT, DEEP], current: { kind: 'namespace', path: 'deep' } });
		await navigated();
		expect(toggleOf('solar-wind')).toHaveAttribute('aria-expanded', 'true');
		expect(within(explorer()).getByRole('link', { name: 'ace' })).toBeInTheDocument();
		expect(within(explorer()).getByRole('link', { name: 'a' })).toBeInTheDocument();
		expect(calls).toHaveLength(1);
	});

	it("drops a folder's failure once the page brings its contents", async () => {
		const calls = stubFetch(jsonResponse({ code: 'UNAVAILABLE' }, 503));
		const shown = await show();
		await fireEvent.click(toggleOf('solar-wind'));
		await within(explorer()).findByRole('button', { name: 'Retry loading solar-wind' });

		shown.rerender({
			levels: [ROOT, SOLAR_WIND],
			current: { kind: 'namespace', path: 'solar-wind' }
		});
		await navigated();
		expect(toggleOf('solar-wind')).toHaveAttribute('aria-expanded', 'true');
		expect(within(explorer()).getByRole('link', { name: 'ace' })).toBeInTheDocument();
		expect(within(explorer()).queryByRole('button', { name: /^Retry/ })).toBeNull();
		expect(screen.queryByText("Couldn't load ·")).toBeNull();
		expect(calls).toHaveLength(1);
	});

	it('opens the way to the current namespace from the levels the server loaded', async () => {
		const calls = stubFetch();
		await show({
			levels: [ROOT, SOLAR_WIND, ACE],
			current: { kind: 'namespace', path: 'solar-wind.ace' }
		});
		const tree = explorer();
		expect(toggleOf('solar-wind')).toHaveAttribute('aria-expanded', 'true');
		expect(toggleOf('ace')).toHaveAttribute('aria-expanded', 'true');
		const ace = within(tree).getByRole('link', { name: 'ace' });
		expect(ace).toHaveAttribute('aria-current', 'page');
		expect(within(tree).getByRole('link', { name: 'Heliophysics' })).not.toHaveAttribute(
			'aria-current'
		);
		expect(within(tree).getByRole('link', { name: 'mag-l2-2024' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.mag-l2-2024'
		);
		expect(calls).toHaveLength(0);
	});

	it('says a level on the way that the server could not load failed, and loads it on Retry', async () => {
		const calls = stubFetch(jsonResponse(SOLAR_WIND));
		await show({
			levels: [ROOT, { parent: 'solar-wind', failed: true }, ACE],
			current: { kind: 'namespace', path: 'solar-wind.ace' }
		});
		expect(toggleOf('solar-wind')).toHaveAttribute('aria-expanded', 'true');
		const retry = within(explorer()).getByRole('button', { name: 'Retry loading solar-wind' });
		expect(retry.closest('p')).toHaveTextContent("Couldn't load · Retry");
		expect(calls).toHaveLength(0);
		await fireEvent.click(retry);
		expect(await within(explorer()).findByRole('link', { name: 'ace' })).toHaveAttribute(
			'aria-current',
			'page'
		);
		expect(screen.queryByText("Couldn't load ·")).toBeNull();
		expect(calls[0].url).toBe('/catalogs/heliophysics/tree?parent=solar-wind');
	});

	it('links what follows a first page to the page that lists it', async () => {
		await show({
			levels: [{ ...ROOT, namespacesNext: 'n2' }, SOLAR_WIND, ACE],
			current: { kind: 'namespace', path: 'solar-wind.ace' }
		});
		expect(
			within(explorer()).getByRole('link', { name: 'More collections in ace' })
		).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/namespaces/solar-wind.ace?collections_cursor=c2'
		);
		const more = within(explorer()).getByRole('link', { name: 'More namespaces in Heliophysics' });
		expect(more).toHaveAttribute('href', '/catalogs/heliophysics?cursor=n2');
		expect(more).toHaveTextContent('More…');
	});

	it('pins the current collection when it is beyond the loaded page', async () => {
		await show({
			levels: [ROOT, SOLAR_WIND, ACE],
			current: { kind: 'collection', namespace: 'solar-wind.ace', name: 'zz-2030', overview: true }
		});
		const leaves = within(toggleOf('ace').closest('li') ?? document.body).getAllByRole('link');
		expect(leaves.map((link) => link.textContent?.trim())).toEqual([
			'ace',
			'mag-l2-2024',
			'swepam-2024',
			'More…',
			'zz-2030'
		]);
		expect(leaves.at(-1)).toHaveAttribute('aria-current', 'page');
		expect(leaves.at(-1)).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/collections/solar-wind.ace.zz-2030'
		);
	});

	it("marks a collection's leaf as the page on its overview, and as its section on a tab", async () => {
		const shown = await show({
			levels: [ROOT, SOLAR_WIND, ACE],
			current: {
				kind: 'collection',
				namespace: 'solar-wind.ace',
				name: 'mag-l2-2024',
				overview: true
			}
		});
		const leaf = () => within(explorer()).getByRole('link', { name: 'mag-l2-2024' });
		expect(leaf()).toHaveAttribute('aria-current', 'page');
		expect(within(explorer()).getByRole('link', { name: 'swepam-2024' })).not.toHaveAttribute(
			'aria-current'
		);
		await shown.rerender({
			current: {
				kind: 'collection',
				namespace: 'solar-wind.ace',
				name: 'mag-l2-2024',
				overview: false
			}
		});
		expect(leaf()).toHaveAttribute('aria-current', 'true');
		expect(within(explorer()).getByRole('link', { name: 'ace' })).not.toHaveAttribute(
			'aria-current'
		);
	});

	it('pins the current namespace when it is beyond the loaded page', async () => {
		await show({
			levels: [ROOT, SOLAR_WIND, { ...ACE, parent: 'solar-wind.zeta', collectionsNext: null }],
			current: { kind: 'namespace', path: 'solar-wind.zeta' }
		});
		const zeta = within(explorer()).getByRole('link', { name: 'zeta' });
		expect(zeta).toHaveAttribute('aria-current', 'page');
		expect(zeta).toHaveAttribute('href', '/catalogs/heliophysics/namespaces/solar-wind.zeta');
		expect(toggleOf('zeta')).toHaveAttribute('aria-expanded', 'true');
	});

	it('opens the way to the page again after navigating there', async () => {
		await show({
			levels: [ROOT, SOLAR_WIND, ACE],
			current: { kind: 'namespace', path: 'solar-wind.ace' }
		});
		await fireEvent.click(toggleOf('solar-wind'));
		expect(within(explorer()).queryByRole('link', { name: 'ace' })).toBeNull();
		await navigated();
		expect(within(explorer()).getByRole('link', { name: 'ace' })).toHaveAttribute(
			'aria-current',
			'page'
		);
	});

	it('lists the current catalog even beyond the first page, and links the rest', async () => {
		await show({ catalogs: [CATALOGS[1]], moreCatalogs: true });
		const links = within(explorer()).getAllByRole('link');
		expect(links[0]).toHaveTextContent('Space Weather');
		expect(links[1]).toHaveTextContent('Heliophysics');
		expect(
			within(explorer()).getByRole('link', { name: 'More catalogs of this organization' })
		).toHaveAttribute('href', '/orgs/helio');
	});

	it('marks the catalog as where the page is on its other tabs', async () => {
		await show({ current: { kind: 'catalog', overview: false } });
		expect(within(explorer()).getByRole('link', { name: 'Heliophysics' })).toHaveAttribute(
			'aria-current',
			'true'
		);
	});
});
