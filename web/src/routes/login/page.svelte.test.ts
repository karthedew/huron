import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { PageData } from './$types';
import Page from './+page.svelte';

function show(data: Partial<PageData> = {}) {
	return render(Page, {
		props: {
			data: { returnTo: '/', status: null, error: null, ...data },
			params: {},
			form: undefined
		}
	});
}

describe('login page', () => {
	it('explains Huron and offers the company sign-in', () => {
		show();
		expect(screen.getByRole('heading', { level: 1, name: 'Sign in to Huron' })).toBeInTheDocument();
		expect(
			screen.getByText('The catalog of raw scientific data on the Huron share.')
		).toBeInTheDocument();
		for (const text of [
			'Browse catalogs, namespaces and collections',
			'Search metadata across your organization',
			'See who can read each catalog',
			'Read-only — use the huron CLI to create collections and push files.'
		]) {
			expect(screen.getByText(text)).toBeInTheDocument();
		}
		const signIn = screen.getByRole('link', { name: 'Sign in with your company account' });
		expect(signIn).toHaveAttribute('href', '/auth/login');
		expect(signIn).toHaveAttribute('data-sveltekit-reload');
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
		expect(screen.queryByRole('status')).not.toBeInTheDocument();
	});

	it('keeps the return path in the sign-in link', () => {
		show({ returnTo: '/orgs/helio?x=1' });
		expect(screen.getByRole('link', { name: 'Sign in with your company account' })).toHaveAttribute(
			'href',
			'/auth/login?returnTo=%2Forgs%2Fhelio%3Fx%3D1'
		);
	});

	it.each([
		['signed-out', "You've signed out.", 'lucide-circle-check'],
		['expired', 'Your session ended. Sign in again to continue.', 'lucide-clock']
	] as const)('shows the %s status', (status, text, icon) => {
		show({ status });
		const line = screen.getByRole('status');
		expect(line).toHaveTextContent(text);
		expect(line.querySelector('svg')).toHaveClass(icon);
	});

	it.each([
		['state_mismatch', 'That sign-in expired or was already used.'],
		['idp_error', "The company sign-in didn't complete."],
		['idp_unavailable', "The company sign-in service isn't responding."],
		['token_rejected', "Huron didn't accept this sign-in."],
		['groups_unavailable', "Huron couldn't read your groups."],
		['service_unavailable', "The Huron service isn't responding."],
		['config', "Sign-in isn't set up correctly. Contact your Huron administrator."]
	] as const)('shows the %s error with Try again', (error, text) => {
		show({ error, returnTo: '/orgs/helio' });
		const alert = screen.getByRole('alert');
		expect(alert).toHaveTextContent(text);
		const retry = screen.getByRole('link', { name: 'Try again' });
		expect(retry).toHaveAttribute('href', '/auth/login?returnTo=%2Forgs%2Fhelio');
		expect(retry).toHaveAttribute('data-sveltekit-reload');
	});
});
