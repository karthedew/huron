import { render, screen } from '@testing-library/svelte';
import type { Component } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Organization } from '$api/types';
import { LINKED_COLLECTION_GONE } from '$lib/error-copy';
import { organizationFixture } from '$lib/testing/api-fixtures';
import InShell from '$lib/testing/InShell.svelte';
import AppError from './(app)/+error.svelte';
import CatalogError from './(app)/catalogs/[catalog=segment]/+error.svelte';
import RootError from './+error.svelte';

const HELIO = organizationFixture();
const GEO = organizationFixture({ id: 'o-geo', name: 'geo', display_name: 'Earth Science' });

const state = vi.hoisted(() => {
	const error: App.Error | null = { message: 'Internal Error' };
	const data: App.PageData = {};
	return {
		page: { status: 500, error, data, url: new URL('http://localhost:4173/orgs/helio?x=1') }
	};
});
vi.mock('$app/state', () => state);

afterEach(() => {
	state.page.status = 500;
	state.page.error = { message: 'Internal Error' };
	state.page.data = {};
});

/** An error page inside the shell, which shows `organization` as the current one. */
function showInShell(organization: Organization | null = null, page: Component = AppError) {
	return render(InShell, { props: { page, organization } });
}

describe.each([
	['the root error page', () => render(RootError)],
	['the error page inside the shell', () => showInShell()],
	['the error page inside a catalog', () => showInShell(null, CatalogError)]
])('%s', (_, show) => {
	it('shows fixed copy for a 404 with the sign-in hint', () => {
		state.page.status = 404;
		show();
		expect(
			screen.getByRole('heading', { level: 1, name: "Not found, or you don't have access." })
		).toBeInTheDocument();
		expect(screen.getByText(/sign out and sign in again/)).toBeInTheDocument();
		expect(screen.queryByRole('link', { name: 'Try again' })).not.toBeInTheDocument();
		expect(document.title).toBe('Not found · Huron');
	});

	it('says that a collection linked by its id may have been deleted', () => {
		state.page.status = 404;
		state.page.error = {
			message: 'Not found, deleted, or you do not have access.',
			code: LINKED_COLLECTION_GONE
		};
		show();
		expect(
			screen.getByRole('heading', {
				level: 1,
				name: 'Not found, deleted, or you do not have access.'
			})
		).toBeInTheDocument();
		expect(screen.getByText(/sign out and sign in again/)).toBeInTheDocument();
	});

	it('offers Try again when the service is unavailable', () => {
		state.page.status = 503;
		state.page.error = { message: 'The API said something private' };
		show();
		expect(
			screen.getByRole('heading', { name: "The Huron service isn't responding." })
		).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Try again' })).toHaveAttribute(
			'href',
			'/orgs/helio?x=1'
		);
		expect(screen.queryByText('The API said something private')).not.toBeInTheDocument();
	});

	it('shows the reference of an internal error', () => {
		state.page.error = { message: 'Internal Error', id: 'req-42' };
		show();
		expect(screen.getByRole('heading', { name: 'Something went wrong.' })).toBeInTheDocument();
		expect(screen.getByText('req-42')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Back to Huron' })).toHaveAttribute('href', '/');
	});

	it("shows no permission's copy for a 403", () => {
		state.page.status = 403;
		show();
		expect(
			screen.getByRole('heading', { name: "You don't have permission to see this." })
		).toBeInTheDocument();
		expect(screen.queryByText(/^Reference/)).not.toBeInTheDocument();
	});
});

describe('the error page inside the shell', () => {
	it("leads back to the shell's current organization", () => {
		state.page.status = 404;
		state.page.data = { organizations: [HELIO, GEO] };
		showInShell(GEO);
		expect(screen.getByRole('link', { name: 'Back to Earth Science' })).toHaveAttribute(
			'href',
			'/orgs/geo'
		);
	});

	it('leads back to the only organization when the shell has no current one', () => {
		state.page.status = 404;
		state.page.data = { organizations: [HELIO] };
		showInShell();
		expect(screen.getByRole('link', { name: 'Back to Heliophysics Division' })).toHaveAttribute(
			'href',
			'/orgs/helio'
		);
	});

	it('leads back to the start page when there is a choice', () => {
		state.page.status = 404;
		state.page.data = { organizations: [HELIO, GEO] };
		showInShell();
		expect(screen.getByRole('link', { name: 'Back to Huron' })).toHaveAttribute('href', '/');
	});
});

describe('the error page inside a catalog', () => {
	it("leads back to the catalog's organization, which the shell shows", () => {
		state.page.status = 404;
		state.page.data = { organizations: [HELIO, GEO], organization: 'geo' };
		showInShell(GEO, CatalogError);
		expect(screen.getByRole('link', { name: 'Back to Earth Science' })).toHaveAttribute(
			'href',
			'/orgs/geo'
		);
	});
});
