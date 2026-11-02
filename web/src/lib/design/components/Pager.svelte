<script lang="ts">
	import { page } from '$app/state';
	import { ChevronRight, ChevronsLeft } from '@lucide/svelte';

	interface Props {
		/** The navigation's name, e.g. "Organization pages". */
		label: string;
		/** The list's `next_cursor`: Next page appears only when there is one. */
		next: string | null | undefined;
		/** The query parameter that carries this list's cursor. */
		param?: string;
		/**
		 * The list's address at a cursor, `null` for its first page, where the list knows its own
		 * (a search's canonical address); by default this page's address with the cursor set.
		 */
		href?: (cursor: string | null) => string;
	}

	let { label, next, param = 'cursor', href }: Props = $props();

	const at = $derived(href ?? ((cursor: string | null) => withCursor(page.url, param, cursor)));
	const nextHref = $derived(next ? at(next) : null);
	const firstHref = $derived(page.url.searchParams.get(param) ? at(null) : null);

	/**
	 * This page's path and query with the list's cursor set, or removed for the first page.
	 * Other parameters stay (a second list's cursor, a search); an old notice does not.
	 */
	function withCursor(url: URL, name: string, cursor: string | null): string {
		const target = new URL(url);
		target.searchParams.delete('notice');
		if (cursor === null) target.searchParams.delete(name);
		else target.searchParams.set(name, cursor);
		return target.pathname + target.search;
	}
</script>

{#if nextHref || firstHref}
	<nav
		aria-label={label}
		class="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-app-line pt-4 text-sm font-semibold"
	>
		{#if firstHref}
			<a href={firstHref} class="inline-flex items-center gap-1.5"
				><ChevronsLeft size={16} aria-hidden="true" />First page</a
			>
		{/if}
		{#if nextHref}
			<a href={nextHref} class="ml-auto inline-flex items-center gap-1.5"
				>Next page<ChevronRight size={16} aria-hidden="true" /></a
			>
		{/if}
	</nav>
{/if}
