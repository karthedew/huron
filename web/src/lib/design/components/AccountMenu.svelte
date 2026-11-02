<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { LogOut, UserRound } from '@lucide/svelte';
	import { HeaderMenu } from './header-menu.svelte';

	interface Props {
		/** The signed-in user, as the session knows them. */
		user: { name: string; subject: string };
	}

	let { user }: Props = $props();

	const menu = new HeaderMenu();
	afterNavigate(menu.close);

	const name = $derived(user.name || user.subject);
	const initials = $derived(
		name
			.split(/\s+/)
			.filter((part) => part !== '')
			.slice(0, 2)
			.map((part) => part[0].toUpperCase())
			.join('')
	);
</script>

<svelte:window onkeydown={menu.keydown} onclick={menu.clickOutside} />

<details
	bind:open={menu.open}
	bind:this={menu.details}
	onfocusout={menu.focusOut}
	class="relative shrink-0"
>
	<!-- The transparent border keeps the circle where forced colors drop its fill. -->
	<summary
		class="no-marker grid size-9 cursor-pointer place-items-center rounded-full border border-transparent bg-brand-ink text-xs font-semibold text-on-ink dark:bg-brand dark:text-brand-ink ring-offset-2 ring-offset-app-bg hover:ring-2 hover:ring-brand"
	>
		<span aria-hidden="true">{initials}</span><span class="sr-only">Account: {name}</span>
	</summary>
	<div
		class="absolute top-full right-0 z-50 mt-2 w-72 overflow-hidden rounded-lg border border-app-line bg-app-raised shadow-menu max-sm:fixed max-sm:inset-x-3 max-sm:top-16 max-sm:w-auto"
	>
		<div class="border-b border-app-line px-4 py-3">
			<p class="m-0 text-sm font-semibold wrap-anywhere text-app-fg">{name}</p>
			<p class="mono m-0 text-xs wrap-anywhere text-app-muted">{user.subject}</p>
		</div>
		<div class="grid gap-0.5 p-1.5">
			<a
				href={resolve('/account')}
				onclick={menu.close}
				class="flex items-center gap-3 rounded-md px-3 py-2.5 text-sm text-app-fg no-underline hover:bg-app-sidebar-hover"
				><UserRound size={16} class="text-app-muted" aria-hidden="true" />Account</a
			>
			<form method="POST" action={resolve('/logout')} class="m-0">
				<button
					type="submit"
					class="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm text-app-fg hover:bg-app-sidebar-hover"
					><LogOut size={16} class="text-app-muted" aria-hidden="true" />Sign out</button
				>
			</form>
		</div>
		<p class="m-0 border-t border-app-line px-4 py-2.5 text-xs text-app-muted">
			Read-only · changes are made with the huron CLI
		</p>
	</div>
</details>
