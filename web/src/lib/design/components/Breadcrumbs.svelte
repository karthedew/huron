<script lang="ts">
	import { ChevronRight } from '@lucide/svelte';

	interface Crumb {
		label: string;
		href: string;
		/** The page itself; at most one crumb is. */
		current?: boolean;
	}

	interface Props {
		crumbs: readonly Crumb[];
	}

	let { crumbs }: Props = $props();
</script>

<nav aria-label="Breadcrumb">
	<ol class="m-0 flex list-none flex-wrap items-center gap-x-1 gap-y-1 p-0 text-sm text-app-muted">
		{#each crumbs as crumb, index (crumb.href)}
			<li class="flex min-w-0 items-center gap-1">
				{#if index > 0}
					<ChevronRight size={14} class="shrink-0" aria-hidden="true" />
				{/if}
				<a
					href={crumb.href}
					aria-current={crumb.current ? 'page' : undefined}
					class={[
						'min-w-0 wrap-anywhere no-underline hover:underline',
						crumb.current ? 'font-semibold text-app-fg' : 'text-app-muted hover:text-app-fg'
					]}>{crumb.label}</a
				>
			</li>
		{/each}
	</ol>
</nav>
