<script lang="ts">
	import { ChevronRight, LogOut, Settings, X } from '@lucide/svelte';
	import type { HuronUser } from '$api/types';
	import { resolve } from '$app/paths';

	interface Props {
		user: HuronUser;
		organization: string;
	}

	let { user, organization }: Props = $props();
	let menu = $state<HTMLDetailsElement>();
	let logoutDialog = $state<HTMLDialogElement>();
	const initials = $derived(
		user.displayName
			.split(/\s+/)
			.map((part) => part[0])
			.join('')
			.slice(0, 2)
			.toUpperCase()
	);

	function openLogout() {
		menu?.removeAttribute('open');
		logoutDialog?.showModal();
	}
</script>

<details class="group relative" bind:this={menu}>
	<summary
		class="grid size-9 cursor-pointer list-none place-items-center rounded-full bg-[#26333b] text-xs font-semibold text-white ring-offset-2 ring-offset-app-bg transition hover:ring-2 hover:ring-brand [&::-webkit-details-marker]:hidden"
		aria-label="Open account menu"
	>
		{initials}
	</summary>

	<div
		class="absolute right-0 top-[calc(100%+0.6rem)] z-50 w-72 overflow-hidden rounded-lg border border-app-line bg-app-raised shadow-[var(--shadow-popover)]"
	>
		<div class="border-b border-app-line p-4">
			<div class="flex items-center gap-3">
				<span
					class="grid size-10 place-items-center rounded-full bg-[#26333b] text-xs font-semibold text-white"
					>{initials}</span
				>
				<div class="min-w-0">
					<p class="truncate text-sm font-semibold">{user.displayName}</p>
					<p class="truncate text-xs text-app-muted">{user.username}</p>
				</div>
			</div>
		</div>
		<div class="p-1.5">
			<a
				href={resolve(
					organization ? `/account?organization=${encodeURIComponent(organization)}` : '/account'
				)}
				onclick={() => menu?.removeAttribute('open')}
				class="flex items-center gap-3 rounded-md px-3 py-2.5 text-sm text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
				><Settings size={16} /><span class="flex-1">User settings</span><ChevronRight
					size={14}
				/></a
			>
			<div class="my-1 border-t border-app-line"></div>
			<button
				type="button"
				onclick={openLogout}
				class="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm text-app-muted hover:bg-app-sidebar-hover hover:text-app-danger"
				><LogOut size={16} /> Log out</button
			>
		</div>
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
			<button type="button" onclick={() => logoutDialog?.close()} aria-label="Close logout dialog"
				><X size={18} class="text-app-muted" /></button
			>
		</div>
		<p class="mt-2 text-sm text-app-muted">
			This ends your current Huron browser session. You’ll need to sign in again before returning to
			the workspace.
		</p>
	</div>
	<form method="POST" action={resolve('/logout')} class="flex justify-end gap-2 p-4">
		<button
			type="button"
			onclick={() => logoutDialog?.close()}
			class="h-9 rounded-md border border-app-line px-3 text-sm font-semibold text-app-muted"
			>Cancel</button
		><button
			type="submit"
			class="inline-flex h-9 items-center gap-2 rounded-md bg-app-danger px-3.5 text-sm font-semibold text-white"
			><LogOut size={15} /> Log out</button
		>
	</form>
</dialog>
