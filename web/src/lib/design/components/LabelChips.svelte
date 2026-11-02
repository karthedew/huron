<script lang="ts">
	import { Check, Search } from '@lucide/svelte';
	import { countLabel } from '$lib/format';
	import type { LabelChip } from '$lib/metadata';
	import { chipFilter, type LabelFilter } from '$lib/search';
	import { ACTIVE_CHIP, CHIPS_MORE, PLAIN_CHIP, SEARCH_CHIP } from '../chips';

	interface Props {
		chips: readonly LabelChip[];
		/** How many more labels there are. */
		more: number;
		/** Where a chip the search can find leads; without it, every chip is text. */
		href?: (label: LabelFilter) => string;
		/** What following that link does, for its name: "search the catalog for this label". */
		action: string;
		/** Whether the search shown already has this filter; such a chip is no link. */
		active?: (label: LabelFilter) => boolean;
		/** The list's name, where nothing else names it. */
		label?: string;
	}

	let { chips, more, href, action, active = () => false, label }: Props = $props();
</script>

<ul class="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label={label}>
	<!-- In their order and not keyed: keys shortened for a list of results may read alike. -->
	{#each chips as chip}
		{@const filter = chipFilter(chip)}
		<li class="max-w-full">
			{#if filter !== null && active(filter)}
				<span class={ACTIVE_CHIP}
					><Check size={12} class="shrink-0 text-brand-strong" aria-hidden="true" /><span
						class="min-w-0"
						>{chip.key}: {chip.value}<span class="sr-only">, in this search</span></span
					></span
				>
			{:else if filter !== null && href !== undefined}
				<!-- Its name starts with what it shows, and says where the link leads. -->
				<a href={href(filter)} aria-label="{chip.key}: {chip.value}, {action}" class={SEARCH_CHIP}
					><Search size={12} class="shrink-0" aria-hidden="true" /><span class="min-w-0"
						>{chip.key}: {chip.value}</span
					></a
				>
			{:else}
				<span class={PLAIN_CHIP}>{chip.key}: {chip.value}</span>
			{/if}
		</li>
	{/each}
	{#if more > 0}<li class={CHIPS_MORE}>and {countLabel(more, 'more label')}</li>{/if}
</ul>
