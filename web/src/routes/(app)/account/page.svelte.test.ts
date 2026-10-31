import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { ROLE_ABILITIES, type RoleSentence } from '$lib/roles';
import { fakeUser } from '$lib/testing/events';
import Page from './+page.svelte';

const state = vi.hoisted(() => ({ page: { url: new URL('http://localhost:4173/account') } }));
vi.mock('$app/state', () => state);

async function show(roleSentences: RoleSentence[] | null, groups = ['helio-contributors']) {
	render(Page, {
		props: {
			data: {
				user: fakeUser({ name: 'Dave Diaz', subject: 'dave', groups }),
				organizations: [],
				organizationsUnavailable: false,
				roles: [],
				rolesUnavailable: false,
				rememberedOrganization: null,
				organization: null,
				roleSentences
			},
			params: {},
			form: undefined
		}
	});
	await tick();
}

const SENTENCES: RoleSentence[] = [
	{
		key: 'platform::platform_admin',
		lead: 'You are a platform administrator',
		target: { kind: 'platform' },
		abilities: `You can ${ROLE_ABILITIES.platform_admin}.`
	},
	{
		key: 'organization:o1:org_admin',
		lead: 'You are an organization administrator of',
		target: { kind: 'organization', name: 'helio', label: 'Heliophysics Division', context: null },
		abilities: `You can ${ROLE_ABILITIES.org_admin}.`
	},
	{
		key: 'catalog:c1:contributor',
		lead: 'You are a contributor to',
		target: {
			kind: 'catalog',
			name: 'heliophysics',
			label: 'Heliophysics',
			context: 'Heliophysics Division'
		},
		abilities: `You can ${ROLE_ABILITIES.contributor}.`
	},
	{
		key: 'catalog:c9:reader',
		lead: 'You are a reader of',
		target: { kind: 'unresolved', label: 'catalog 00000000abcd' },
		abilities: `You can ${ROLE_ABILITIES.reader}.`
	}
];

describe('/account page', () => {
	it('shows who is signed in, until when, and offers to sign out', async () => {
		await show(SENTENCES);
		expect(screen.getByRole('heading', { level: 1, name: 'Account' })).toBeInTheDocument();
		const you = screen.getByRole('region', { name: 'Signed in' });
		expect(within(you).getByText('Dave Diaz')).toBeInTheDocument();
		expect(within(you).getByText('dave')).toBeInTheDocument();
		const ends = within(you).getByText('2026-10-29 18:00 UTC');
		expect(ends).toHaveAttribute('datetime', '2026-10-29T18:00:00.000Z');
		const signOut = within(you).getByRole('button', { name: 'Sign out' });
		expect(signOut.closest('form')).toHaveAttribute('action', '/logout');
		expect(signOut.closest('form')).toHaveAttribute('method', 'POST');
		expect(document.title).toBe('Account · Huron');
	});

	it('lists the groups as of sign-in with the re-sign-in hint', async () => {
		await show(SENTENCES, ['geo-readers', 'helio-contributors']);
		const groups = screen.getByRole('region', { name: 'Groups' });
		expect(groups).toHaveTextContent('As of sign-in at 2026-10-29 10:00 UTC:');
		expect(
			within(groups)
				.getAllByRole('listitem')
				.map((item) => item.textContent)
		).toEqual(['geo-readers', 'helio-contributors']);
		expect(groups).toHaveTextContent(
			'Groups are read when you sign in; if you were just added to a group, sign out and sign in again.'
		);
	});

	it('says when Huron received no groups', async () => {
		await show([], []);
		expect(screen.getByText('Huron received no groups for your account.')).toBeInTheDocument();
		expect(screen.getByText('Your groups hold no roles in Huron.')).toBeInTheDocument();
	});

	it('describes each role as a sentence with links to its scope', async () => {
		await show(SENTENCES);
		const roles = screen.getByRole('region', { name: 'Roles' });
		const items = within(roles).getAllByRole('listitem');
		expect(items.map((item) => item.querySelector('p')?.textContent?.replace(/\s+/g, ' '))).toEqual(
			[
				'You are a platform administrator.',
				'You are an organization administrator of Heliophysics Division.',
				'You are a contributor to Heliophysics in Heliophysics Division.',
				'You are a reader of catalog 00000000abcd.'
			]
		);
		expect(within(items[1]).getByRole('link', { name: 'Heliophysics Division' })).toHaveAttribute(
			'href',
			'/orgs/helio'
		);
		expect(within(items[2]).getByRole('link', { name: 'Heliophysics' })).toHaveAttribute(
			'href',
			'/catalogs/heliophysics'
		);
		expect(within(items[3]).queryByRole('link')).not.toBeInTheDocument();
		expect(items[2]).toHaveTextContent(`You can ${ROLE_ABILITIES.contributor}.`);
	});

	it('offers to try again when the roles could not be loaded', async () => {
		await show(null);
		const roles = screen.getByRole('region', { name: 'Roles' });
		expect(roles).toHaveTextContent("Your roles couldn't be loaded.");
		expect(within(roles).getByRole('link', { name: 'Try again' })).toHaveAttribute(
			'href',
			'/account'
		);
	});

	it('shows how to sign in with the CLI, without server addresses', async () => {
		await show(SENTENCES);
		const cli = screen.getByRole('region', { name: 'Sign in and see what Huron knows about you' });
		expect(within(cli).getByRole('textbox')).toHaveValue('huron login\nhuron whoami');
		expect(cli.textContent).not.toMatch(/https?:/);
	});
});
