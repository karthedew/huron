import { cleanup, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { Organization } from '$api/types';
import { emptySearch, type Search, type SearchErrors } from '$lib/search';
import { organizationFixture } from '$lib/testing/api-fixtures';
import { fakeUser } from '$lib/testing/events';
import Page from './+page.svelte';

vi.mock('$app/state', () => import('$lib/testing/app-state.svelte'));

const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });
const NO_ERRORS: SearchErrors = { q: null, label: null, form: null };

function show({
	search = emptySearch(),
	errors = NO_ERRORS,
	organizationList = [GEO, HELIO],
	groups = ['helio-readers']
}: {
	search?: Search;
	errors?: SearchErrors;
	organizationList?: Organization[];
	groups?: string[];
} = {}) {
	return render(Page, {
		props: {
			data: {
				user: fakeUser({ groups }),
				organizations: organizationList,
				organizationsUnavailable: false,
				roles: [],
				rolesUnavailable: false,
				rememberedOrganization: null,
				organization: null,
				organizationList,
				search,
				errors
			},
			params: {},
			form: undefined
		}
	});
}

/** The organizations offered, by name and where each leads. */
function offered(): Array<[string | null, string | null]> {
	const list = screen.getByRole('list', { name: 'Organizations' });
	return within(list)
		.getAllByRole('link')
		.map((link) => [link.textContent, link.getAttribute('href')]);
}

describe('the page that asks which organization to search', () => {
	it("offers each organization's search for the text and its labels", () => {
		show({
			search: { ...emptySearch(), q: 'wind', labels: [{ key: 'mission', value: 'ace' }] }
		});
		expect(document.title).toBe('“wind” · Search · Huron');
		expect(screen.getByRole('heading', { level: 1, name: 'Search' })).toBeInTheDocument();
		expect(screen.getByText('Search “wind” with mission = ace in:')).toBeInTheDocument();
		expect(offered()).toEqual([
			['Earth Science', '/orgs/geo/search?q=wind&label=mission%3Dace'],
			['Heliophysics Division', '/orgs/helio/search?q=wind&label=mission%3Dace']
		]);
	});

	it('asks which organization to search for no text at all', () => {
		const { unmount } = show();
		expect(document.title).toBe('Search · Huron');
		expect(screen.getByText('Choose the organization to search:')).toBeInTheDocument();
		expect(offered()).toEqual([
			['Earth Science', '/orgs/geo/search'],
			['Heliophysics Division', '/orgs/helio/search']
		]);
		unmount();
		show({ search: { ...emptySearch(), labels: [{ key: 'level', value: 'l2' }] } });
		expect(screen.getByText('Search with level = l2 in:')).toBeInTheDocument();
	});

	it('says why it left part of the address out', () => {
		show({ errors: { ...NO_ERRORS, q: 'Use at most 200 characters; this text has 201.' } });
		expect(document.title).toBe('Error: Search · Huron');
		expect(screen.getByText('Use at most 200 characters; this text has 201.')).toBeInTheDocument();
		expect(offered()).toHaveLength(2);
	});

	it('says why for each part it left out, the text and the labels alike', () => {
		show({
			errors: {
				...NO_ERRORS,
				q: 'Use at most 200 characters; this text has 201.',
				label: 'Write a label filter as key=value, for example mission=ace.'
			}
		});
		expect(document.title).toBe('Error: Search · Huron');
		expect(screen.getByText('Use at most 200 characters; this text has 201.')).toBeInTheDocument();
		expect(
			screen.getByText('Write a label filter as key=value, for example mission=ace.')
		).toBeInTheDocument();
		expect(screen.getByText('Choose the organization to search:')).toBeInTheDocument();
		expect(offered()).toEqual([
			['Earth Science', '/orgs/geo/search'],
			['Heliophysics Division', '/orgs/helio/search']
		]);
	});

	it('repeats no more of a long search than each of many links may hold, and says so', () => {
		const many = Array.from({ length: 500 }, (_, index) =>
			organizationFixture({ id: `o-${index}`, name: `org-${index}`, display_name: '' })
		);
		const labels = Array.from({ length: 6 }, (_, index) => ({
			key: `${index}${'𝕏'.repeat(99)}`,
			value: '𝕏'.repeat(100)
		}));
		show({ search: { ...emptySearch(), q: 'wind', labels }, organizationList: many });
		expect(
			screen.getByText(
				'This search is too long to repeat in a link to each organization, so the links leave out its label filters.'
			)
		).toBeInTheDocument();
		// The lead says what the links search for.
		expect(screen.getByText('Search “wind” in:')).toBeInTheDocument();
		const links = offered();
		expect(links).toHaveLength(500);
		expect(links[0]).toEqual(['org-0', '/orgs/org-0/search?q=wind']);
		// With two organizations, each link may hold the whole search.
		cleanup();
		show({ search: { ...emptySearch(), q: 'wind', labels } });
		expect(screen.queryByText(/too long to repeat/)).toBeNull();
		expect(offered()[0][1]).toMatch(/^\/orgs\/geo\/search\?q=wind(&label=[^&]+){6}$/);
	});

	it('tells someone who can see no organization why, as the start page does', () => {
		show({ organizationList: [], groups: [] });
		expect(screen.getByText("You don't have access to any organization yet.")).toBeInTheDocument();
		expect(screen.getByText('Huron received no groups for your account.')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
		expect(screen.queryByRole('list', { name: 'Organizations' })).toBeNull();
	});
});
