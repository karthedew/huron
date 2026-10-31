import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SiteSearch from './SiteSearch.svelte';

function show({
	action = '/catalogs/heliophysics/search',
	name = 'Heliophysics',
	q = ''
}: { action?: string; name?: string | null; q?: string } = {}) {
	return render(SiteSearch, { props: { action, name, q } });
}

function form(): HTMLFormElement {
	const found = screen.getByRole('search', { name: 'Site search' });
	if (!(found instanceof HTMLFormElement)) throw new Error('the search is no form');
	return found;
}

/** What the form submits once the browser has read it, scripts tidying it. */
function submitted(): Array<[string, FormDataEntryValue]> {
	const data = new FormData(form());
	// jsdom fires no formdata event of its own; browsers do, on every read of the form.
	const event = new Event('formdata');
	Object.defineProperty(event, 'formData', { value: data });
	form().dispatchEvent(event);
	return [...data];
}

describe('the site search box', () => {
	it('is a search landmark of one field, sent by GET to the page it searches', () => {
		show();
		expect(form()).toHaveAttribute('method', 'GET');
		expect(form()).toHaveAttribute('action', '/catalogs/heliophysics/search');
		expect(form().elements).toHaveLength(1);
		expect(screen.queryByRole('combobox')).toBeNull();
	});

	it('names its field after what it searches', () => {
		const { unmount } = show({ name: 'Heliophysics Division', action: '/orgs/helio/search' });
		const field = screen.getByRole('searchbox', { name: 'Search Heliophysics Division' });
		expect(field).toHaveAttribute('name', 'q');
		expect(field).toHaveAttribute('placeholder', 'Search Heliophysics Division…');
		unmount();
		show({ name: null, action: '/search' });
		expect(screen.getByRole('searchbox', { name: 'Search' })).toHaveAttribute(
			'placeholder',
			'Search…'
		);
	});

	it('holds at most 200 characters, and the text of the search shown', () => {
		show({ q: 'solar wind' });
		const field = screen.getByRole('searchbox', { name: 'Search Heliophysics' });
		expect(field).toHaveAttribute('maxlength', '200');
		expect(field).toHaveValue('solar wind');
	});

	it('submits the text trimmed, and nothing for no text', () => {
		show();
		const field = screen.getByRole('searchbox', { name: 'Search Heliophysics' });
		if (!(field instanceof HTMLInputElement)) throw new Error('no field');
		field.value = '  solar wind ';
		expect(submitted()).toEqual([['q', 'solar wind']]);
		field.value = '   ';
		expect(submitted()).toEqual([]);
	});
});
