import { render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Pager from './Pager.svelte';

const state = vi.hoisted(() => ({ page: { url: new URL('http://localhost:4173/orgs') } }));
vi.mock('$app/state', () => state);

afterEach(() => {
	state.page.url = new URL('http://localhost:4173/orgs');
});

function show(
	path: string,
	next: string | null | undefined,
	param?: string,
	href?: (cursor: string | null) => string
) {
	state.page.url = new URL(`http://localhost:4173${path}`);
	return render(Pager, { props: { label: 'Organization pages', next, param, href } });
}

describe('Pager', () => {
	it('renders nothing for a single page', () => {
		show('/orgs', null);
		expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
		show('/orgs', undefined);
		expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
	});

	it('offers the next page from the first one', () => {
		show('/orgs?notice=page_expired&q=x', 'c2');
		const pages = screen.getByRole('navigation', { name: 'Organization pages' });
		expect(pages).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/orgs?q=x&cursor=c2'
		);
		expect(screen.queryByRole('link', { name: 'First page' })).not.toBeInTheDocument();
	});

	it('offers the first page from a later one, also when it is the last', () => {
		show('/orgs?cursor=c2&q=x', 'c3');
		expect(screen.getByRole('link', { name: 'First page' })).toHaveAttribute('href', '/orgs?q=x');
		expect(screen.getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/orgs?cursor=c3&q=x'
		);
	});

	it('decides by the cursor alone, not by how full the page is', () => {
		show('/orgs?cursor=c9', null);
		expect(screen.getByRole('link', { name: 'First page' })).toHaveAttribute('href', '/orgs');
		expect(screen.queryByRole('link', { name: 'Next page' })).not.toBeInTheDocument();
	});

	it('links the pages a list gives addresses of its own', () => {
		show('/search?state=active&q=x&cursor=c2', 'c3', undefined, (cursor) =>
			cursor === null ? '/search?q=x' : `/search?q=x&cursor=${cursor}`
		);
		expect(screen.getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/search?q=x&cursor=c3'
		);
		expect(screen.getByRole('link', { name: 'First page' })).toHaveAttribute('href', '/search?q=x');
	});

	it("pages one list of several and keeps the other list's cursor", () => {
		show(
			'/catalogs/h/namespaces/n?namespaces_cursor=a&collections_cursor=b',
			'b2',
			'collections_cursor'
		);
		expect(screen.getByRole('link', { name: 'Next page' })).toHaveAttribute(
			'href',
			'/catalogs/h/namespaces/n?namespaces_cursor=a&collections_cursor=b2'
		);
		expect(screen.getByRole('link', { name: 'First page' })).toHaveAttribute(
			'href',
			'/catalogs/h/namespaces/n?namespaces_cursor=a'
		);
	});
});
