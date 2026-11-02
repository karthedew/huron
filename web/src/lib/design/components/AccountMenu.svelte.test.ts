import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AccountMenu from './AccountMenu.svelte';

const navigation = vi.hoisted(() => ({ callbacks: new Array<() => void>() }));
vi.mock('$app/navigation', () => ({
	afterNavigate: (callback: () => void) => navigation.callbacks.push(callback)
}));

afterEach(() => {
	navigation.callbacks.length = 0;
});

function show(user = { name: 'Dave Diaz', subject: 'dave' }) {
	render(AccountMenu, { props: { user } });
	const details = document.querySelector('details');
	const summary = details?.querySelector('summary');
	if (!details || !(summary instanceof HTMLElement)) throw new Error('no account menu');
	return { details, summary };
}

async function open(details: HTMLDetailsElement, summary: HTMLElement) {
	const toggled = new Promise((resolve) =>
		details.addEventListener('toggle', resolve, { once: true })
	);
	await fireEvent.click(summary);
	await toggled;
	await tick();
}

describe('AccountMenu', () => {
	it("shows the user's initials and names the menu after them", () => {
		const { summary } = show();
		expect(summary).toHaveTextContent('DDAccount: Dave Diaz');
		expect(summary.querySelector('[aria-hidden="true"]')).toHaveTextContent('DD');
	});

	it('holds the name, the subject, the account page and a plain logout form', async () => {
		const { details, summary } = show();
		await open(details, summary);
		expect(screen.getByText('Dave Diaz')).toBeInTheDocument();
		expect(screen.getByText('dave')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Account' })).toHaveAttribute('href', '/account');
		const logOut = screen.getByRole('button', { name: 'Sign out' });
		expect(logOut).toHaveAttribute('type', 'submit');
		const form = logOut.closest('form');
		expect(form).toHaveAttribute('method', 'POST');
		expect(form).toHaveAttribute('action', '/logout');
		expect(screen.getByText('Read-only · changes are made with the huron CLI')).toBeInTheDocument();
	});

	it('falls back to the subject without a name', () => {
		const { summary } = show({ name: '', subject: 'mallory' });
		expect(summary).toHaveTextContent('MAccount: mallory');
	});

	it('closes on Escape, on a click outside and after a navigation', async () => {
		const { details, summary } = show();
		await open(details, summary);
		screen.getByRole('link', { name: 'Account' }).focus();
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(details.open).toBe(false);
		expect(document.activeElement).toBe(summary);

		await open(details, summary);
		await fireEvent.click(document.body);
		expect(details.open).toBe(false);

		await open(details, summary);
		for (const callback of navigation.callbacks) callback();
		await tick();
		expect(details.open).toBe(false);
	});

	it('moves between its link and the logout button with the arrow keys, Home and End', async () => {
		const { details, summary } = show();
		await open(details, summary);
		summary.focus();
		const account = screen.getByRole('link', { name: 'Account' });
		const logOut = screen.getByRole('button', { name: 'Sign out' });
		const press = async (key: string) => {
			await fireEvent.keyDown(document.activeElement ?? window, { key });
			return document.activeElement;
		};
		expect(await press('ArrowDown')).toBe(account);
		expect(await press('ArrowDown')).toBe(logOut);
		expect(await press('ArrowDown')).toBe(account);
		expect(await press('ArrowUp')).toBe(logOut);
		expect(await press('Home')).toBe(account);
		expect(await press('End')).toBe(logOut);
	});
});
