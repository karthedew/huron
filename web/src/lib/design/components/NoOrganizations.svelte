<script lang="ts">
	import { resolve } from '$app/paths';
	import EmptyState from './EmptyState.svelte';

	interface Props {
		/** The user's groups as of sign-in. */
		groups: readonly string[];
	}

	let { groups }: Props = $props();
</script>

<EmptyState title="You don't have access to any organization yet.">
	<div class="mt-3 grid gap-3 text-sm">
		{#if groups.length > 0}
			<p class="m-0">Your groups as of sign-in:</p>
			<ul class="m-0 flex list-none flex-wrap justify-center gap-1.5 p-0">
				{#each groups as group (group)}
					<li><code class="break-all">{group}</code></li>
				{/each}
			</ul>
		{:else}
			<p class="m-0">Huron received no groups for your account.</p>
		{/if}
		<p class="m-0">
			Groups are read when you sign in; if you were just added to a group, sign out and sign in
			again.
		</p>
		<form method="POST" action={resolve('/logout')} class="m-0">
			<button
				type="submit"
				class="h-9 rounded-md border border-app-line bg-app-card px-3 font-semibold text-app-fg hover:border-app-line-strong"
				>Sign out</button
			>
		</form>
	</div>
</EmptyState>
