<script lang="ts">
	import { ChevronRight, KeyRound, LogIn, LogOut, Settings, UserRound, X } from '@lucide/svelte';
	import { onMount } from 'svelte';
	import type { WhoAmI } from '$api/types';

	interface Props {
		user: WhoAmI;
	}

	let { user }: Props = $props();
	let menu: HTMLDetailsElement;
	let logoutDialog: HTMLDialogElement;
	let signedOut = $state(false);
	const initials = $derived(
		user.displayName
			.split(/\s+/)
			.map((part) => part[0])
			.join('')
			.slice(0, 2)
			.toUpperCase()
	);

	onMount(() => {
		signedOut = sessionStorage.getItem('huron-preview-signed-out') === 'true';
	});

	function openLogout() {
		menu.removeAttribute('open');
		logoutDialog.showModal();
	}

	function signOut() {
		sessionStorage.setItem('huron-preview-signed-out', 'true');
		window.location.assign('/account?status=signed-out');
	}

	function signIn() {
		sessionStorage.removeItem('huron-preview-signed-out');
		window.location.assign('/account');
	}
</script>

<details class="group relative" bind:this={menu}>
	<summary
		class="grid size-9 cursor-pointer list-none place-items-center rounded-full bg-[#26333b] text-xs font-semibold text-white ring-offset-2 ring-offset-app-bg transition hover:ring-2 hover:ring-brand [&::-webkit-details-marker]:hidden"
		aria-label="Open account menu"
	>
		{#if signedOut}<UserRound size={16} />{:else}{initials}{/if}
	</summary>

	<div
		class="absolute right-0 top-[calc(100%+0.6rem)] z-50 w-72 overflow-hidden rounded-lg border border-app-line bg-app-raised shadow-[var(--shadow-popover)]"
	>
		{#if signedOut}
			<div class="p-4">
				<div class="flex items-center gap-3">
					<span
						class="grid size-10 place-items-center rounded-full border border-app-line bg-app-bg text-app-muted"
						><UserRound size={18} /></span
					>
					<div>
						<p class="text-sm font-semibold">Signed out</p>
						<p class="text-xs text-app-muted">Fixture workspace session</p>
					</div>
				</div>
				<button
					type="button"
					onclick={signIn}
					class="mt-4 inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-brand text-sm font-semibold text-[#062d29]"
					><LogIn size={15} /> Sign in again</button
				>
			</div>
		{:else}
			<div class="border-b border-app-line p-4">
				<div class="flex items-center gap-3">
					<span
						class="grid size-10 place-items-center rounded-full bg-[#26333b] text-xs font-semibold text-white"
						>{initials}</span
					>
					<div class="min-w-0">
						<p class="truncate text-sm font-semibold">{user.displayName}</p>
						<p class="truncate text-xs text-app-muted">{user.subject}</p>
					</div>
				</div>
			</div>
			<div class="p-1.5">
				<a
					href="/account"
					onclick={() => menu.removeAttribute('open')}
					class="flex items-center gap-3 rounded-md px-3 py-2.5 text-sm text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
					><Settings size={16} /><span class="flex-1">User settings</span><ChevronRight
						size={14}
					/></a
				>
				<a
					href="/account?tab=api-keys"
					onclick={() => menu.removeAttribute('open')}
					class="flex items-center gap-3 rounded-md px-3 py-2.5 text-sm text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
					><KeyRound size={16} /><span class="flex-1">API keys</span><ChevronRight size={14} /></a
				>
				<div class="my-1 border-t border-app-line"></div>
				<button
					type="button"
					onclick={openLogout}
					class="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm text-app-muted hover:bg-app-sidebar-hover hover:text-app-danger"
					><LogOut size={16} /> Log out</button
				>
			</div>
		{/if}
	</div>
</details>

<dialog
	bind:this={logoutDialog}
	aria-label="Log out of Huron?"
	class="m-auto w-[min(92vw,440px)] rounded-xl border border-app-line bg-app-raised p-0 text-app-fg shadow-[var(--shadow-popover)] backdrop:bg-black/45"
>
	<div class="border-b border-app-line p-5">
		<div class="flex items-center justify-between">
			<h2 class="m-0 border-0 p-0 text-lg font-semibold">Log out of Huron?</h2>
			<button type="button" onclick={() => logoutDialog.close()} aria-label="Close logout dialog"
				><X size={18} class="text-app-muted" /></button
			>
		</div>
		<p class="mt-2 text-sm text-app-muted">
			This signs you out of the fixture workspace. Production logout will hand off to the configured
			OIDC provider.
		</p>
	</div>
	<div class="flex justify-end gap-2 p-4">
		<button
			type="button"
			onclick={() => logoutDialog.close()}
			class="h-9 rounded-md border border-app-line px-3 text-sm font-semibold text-app-muted"
			>Cancel</button
		><button
			type="button"
			onclick={signOut}
			class="inline-flex h-9 items-center gap-2 rounded-md bg-app-danger px-3.5 text-sm font-semibold text-white"
			><LogOut size={15} /> Log out</button
		>
	</div>
</dialog>
