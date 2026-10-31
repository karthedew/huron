import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { emptySearch, searchQuery, type Search, type SearchErrors } from '$lib/search';
import SearchForm from './SearchForm.svelte';

const NO_ERRORS: SearchErrors = { q: null, label: null, form: null };

function show({
	search = emptySearch(),
	errors = NO_ERRORS,
	pendingLabel = '',
	drafts = false
}: {
	search?: Search;
	errors?: SearchErrors;
	pendingLabel?: string;
	drafts?: boolean;
} = {}) {
	return render(SearchForm, {
		props: {
			label: 'Catalog search',
			action: '/catalogs/heliophysics/search',
			search,
			errors,
			pendingLabel,
			drafts,
			href: (other: Search) => `/catalogs/heliophysics/search${searchQuery(other)}`
		}
	});
}

function form(): HTMLFormElement {
	const found = screen.getByRole('search', { name: 'Catalog search' });
	if (!(found instanceof HTMLFormElement)) throw new Error('the search is no form');
	return found;
}

function checkbox(name: string): HTMLInputElement {
	const found = screen.getByRole('checkbox', { name });
	if (!(found instanceof HTMLInputElement)) throw new Error(`${name} is no input`);
	return found;
}

const FILTERED: Search = {
	q: 'wind',
	labels: [
		{ key: 'mission', value: 'wind' },
		{ key: 'level', value: 'l2' }
	],
	states: ['incomplete'],
	cursor: 'c2'
};

describe('the search form', () => {
	it('is a search landmark that submits to the page by GET', () => {
		show();
		expect(form()).toHaveAttribute('method', 'GET');
		expect(form()).toHaveAttribute('action', '/catalogs/heliophysics/search');
		expect(screen.getByRole('button', { name: 'Search' })).toHaveAttribute('type', 'submit');
	});

	it('holds the text, at most 200 characters, and explains what it matches', () => {
		show({ search: FILTERED });
		const text = screen.getByRole('searchbox', { name: 'Search text' });
		expect(text).toHaveValue('wind');
		expect(text).toHaveAttribute('name', 'q');
		expect(text).toHaveAttribute('maxlength', '200');
		expect(text).not.toHaveAttribute('aria-invalid');
		expect(text).toHaveAccessibleDescription(
			'Matches the exact text in identifiers, titles and descriptions. Use labels for exact key=value filters. Sorted by identifier.'
		);
	});

	it('shows each label filter as a link that removes it, and submits it again', () => {
		show({ search: FILTERED });
		const filters = within(screen.getByRole('list', { name: 'Label filters' })).getAllByRole(
			'link'
		);
		expect(filters.map((link) => [link.getAttribute('aria-label'), link.textContent])).toEqual([
			['Remove filter mission = wind', 'mission = wind'],
			['Remove filter level = l2', 'level = l2']
		]);
		// The text and the states stay; the page starts again at the first one.
		expect(filters[0]).toHaveAttribute(
			'href',
			'/catalogs/heliophysics/search?q=wind&label=level%3Dl2&state=incomplete'
		);
		const hidden = [...form().querySelectorAll('input[type="hidden"]')];
		expect(
			hidden.map((input) => [input.getAttribute('name'), input.getAttribute('value')])
		).toEqual([
			['label', 'mission=wind'],
			['label', 'level=l2']
		]);
	});

	it('keeps a filter with a line break as JSON, which a browser submits as it is', () => {
		show({
			search: {
				...emptySearch(),
				labels: [
					{ key: 'note', value: 'two\nlines' },
					{ key: 'mission', value: 'wind' }
				]
			}
		});
		const hidden = [...form().querySelectorAll('input[type="hidden"]')];
		expect(
			hidden.map((input) => [input.getAttribute('name'), input.getAttribute('value')])
		).toEqual([
			['label_json', '"note=two\\nlines"'],
			['label', 'mission=wind']
		]);
		// Scripts submit it as a label again.
		const data = new FormData(form());
		const event = new Event('formdata');
		Object.defineProperty(event, 'formData', { value: data });
		form().dispatchEvent(event);
		expect(data.getAll('label')).toEqual(['note=two\nlines', 'mission=wind']);
		expect(data.has('label_json')).toBe(false);
	});

	it('offers one field for adding a label filter', () => {
		show({ search: FILTERED });
		const add = screen.getByRole('textbox', { name: 'Add a label filter' });
		expect(add).toHaveAttribute('name', 'label');
		expect(add).toHaveValue('');
		expect(add).toHaveAttribute('placeholder', 'key=value');
		expect(screen.getByRole('group', { name: 'Labels' })).toContainElement(add);
	});

	it('lists no filters for a search without labels', () => {
		show();
		expect(screen.queryByRole('list', { name: 'Label filters' })).toBeNull();
		expect(form().querySelectorAll('input[type="hidden"]')).toHaveLength(0);
	});

	it('checks Active and Incomplete when the search names no states', () => {
		show();
		expect(checkbox('Active').checked).toBe(true);
		expect(checkbox('Incomplete').checked).toBe(true);
		expect(checkbox('Active')).toHaveAttribute('name', 'state');
		expect(checkbox('Active')).toHaveAttribute('value', 'active');
		expect(screen.getByRole('group', { name: 'States' })).toContainElement(checkbox('Active'));
	});

	it('checks the states the search names', () => {
		show({ search: FILTERED });
		expect(checkbox('Active').checked).toBe(false);
		expect(checkbox('Incomplete').checked).toBe(true);
	});

	it('offers Draft only to those who may see drafts', () => {
		const { unmount } = show();
		expect(screen.queryByRole('checkbox', { name: 'Draft' })).toBeNull();
		expect(screen.getAllByRole('checkbox')).toHaveLength(2);
		unmount();
		show({ search: { ...emptySearch(), states: ['active', 'draft'] }, drafts: true });
		expect(checkbox('Draft').checked).toBe(true);
		expect(checkbox('Draft')).toHaveAttribute('value', 'draft');
	});

	it('shows a text it cannot search at its field', () => {
		show({
			search: { ...emptySearch(), q: 'w'.repeat(201) },
			errors: { ...NO_ERRORS, q: 'Use at most 200 characters; this text has 201.' }
		});
		const text = screen.getByRole('searchbox', { name: 'Search text' });
		expect(text).toHaveAttribute('aria-invalid', 'true');
		expect(text).toHaveValue('w'.repeat(201));
		expect(text).toHaveAccessibleDescription(
			/^Use at most 200 characters; this text has 201\. Matches the exact text/
		);
		expect(screen.getByRole('textbox', { name: 'Add a label filter' })).not.toHaveAttribute(
			'aria-invalid'
		);
	});

	it('gives back a label it cannot read in the field for adding one, with why', () => {
		show({
			pendingLabel: 'mission',
			errors: { ...NO_ERRORS, label: 'Write a label filter as key=value, for example mission=ace.' }
		});
		const add = screen.getByRole('textbox', { name: 'Add a label filter' });
		expect(add).toHaveValue('mission');
		expect(add).toHaveAttribute('aria-invalid', 'true');
		expect(add).toHaveAccessibleDescription(
			'Write a label filter as key=value, for example mission=ace.'
		);
		expect(screen.getByRole('searchbox', { name: 'Search text' })).not.toHaveAttribute(
			'aria-invalid'
		);
	});

	it('describes the form with a refusal that names no field', () => {
		show({ errors: { ...NO_ERRORS, form: "The Huron service didn't accept this search." } });
		expect(form()).toHaveAccessibleDescription("The Huron service didn't accept this search.");
	});

	it('submits the canonical query when the browser reads the form', () => {
		show({ search: FILTERED });
		const data = new FormData(form());
		// jsdom fires no formdata event of its own; browsers do, on every read of the form.
		const event = new Event('formdata');
		Object.defineProperty(event, 'formData', { value: data });
		form().dispatchEvent(event);
		expect([...data]).toEqual([
			['q', 'wind'],
			['label', 'mission=wind'],
			['label', 'level=l2'],
			['state', 'incomplete']
		]);
	});

	it('shows the search it is given afresh, whatever was typed before', async () => {
		const { rerender } = show({ search: FILTERED });
		const text = screen.getByRole('searchbox', { name: 'Search text' });
		const add = screen.getByRole('textbox', { name: 'Add a label filter' });
		if (!(text instanceof HTMLInputElement) || !(add instanceof HTMLInputElement)) {
			throw new Error('no fields');
		}
		text.value = 'typed, not searched';
		add.value = 'instrument=mag';
		checkbox('Active').checked = true;
		await rerender({
			search: { ...FILTERED, labels: [...FILTERED.labels, { key: 'instrument', value: 'mag' }] }
		});
		expect(screen.getByRole('searchbox', { name: 'Search text' })).toHaveValue('wind');
		expect(screen.getByRole('textbox', { name: 'Add a label filter' })).toHaveValue('');
		expect(checkbox('Active').checked).toBe(false);
		expect(
			within(screen.getByRole('list', { name: 'Label filters' })).getAllByRole('link')
		).toHaveLength(3);
	});
});
