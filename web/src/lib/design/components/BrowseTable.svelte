<script lang="ts">
	import { page } from '$app/state';
	import { ArrowDown, ArrowUp, ArrowUpDown } from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import { browseSortHref, type BrowseColumn, type BrowseSort } from '$lib/browse-sort';
	import ScrollRegion from './ScrollRegion.svelte';

	interface Props {
		label: string;
		sort: BrowseSort;
		/** The list's query prefix on a page with independent namespace and collection lists. */
		prefix?: string;
		/** Numeric content columns displayed after the name; these are not sortable. */
		countColumns?: readonly string[];
		children: Snippet;
	}

	let { label, sort, prefix = '', countColumns = [], children }: Props = $props();
	const columns: readonly { key: BrowseColumn; label: string }[] = [
		{ key: 'name', label: 'Name' },
		{ key: 'created_by', label: 'Created by' },
		{ key: 'created_at', label: 'Created at' }
	];
</script>

<ScrollRegion label="{label} table">
	<table
		class={[
			'w-full table-fixed border-collapse text-left text-sm',
			countColumns.length ? 'min-w-192' : 'min-w-160'
		]}
		aria-label={label}
	>
		<colgroup>
			<col />
			{#each countColumns as column (column)}<col class="w-28" />{/each}
			<col class="w-40" /><col class="w-48" />
		</colgroup>
		<thead>
			<tr class="bg-app-raised">
				{#each columns as column (column.key)}
					{@const selected = sort.sort === column.key}
					<th
						scope="col"
						aria-sort={selected ? (sort.order === 'asc' ? 'ascending' : 'descending') : undefined}
						class="border-r border-b border-app-line px-4 py-2 font-semibold last:border-r-0"
					>
						<a
							href={browseSortHref(page.url, column.key, prefix)}
							onfocus={(event) =>
								event.currentTarget.scrollIntoView({ block: 'nearest', inline: 'nearest' })}
							aria-label="Sort by {column.label} {selected && sort.order === 'asc'
								? 'descending'
								: 'ascending'}"
							class="inline-flex scroll-m-2 items-center gap-2 text-app-fg no-underline hover:underline"
						>
							{column.label}
							{#if selected && sort.order === 'asc'}<ArrowUp size={14} aria-hidden="true" />
							{:else if selected}<ArrowDown size={14} aria-hidden="true" />
							{:else}<ArrowUpDown size={14} class="text-app-muted" aria-hidden="true" />{/if}
						</a>
					</th>
					{#if column.key === 'name'}
						{#each countColumns as countColumn (countColumn)}
							<th
								scope="col"
								class="border-r border-b border-app-line px-4 py-2 text-right font-semibold"
								>{countColumn}</th
							>
						{/each}
					{/if}
				{/each}
			</tr>
		</thead>
		<tbody>{@render children()}</tbody>
	</table>
</ScrollRegion>
