<script lang="ts">
	import { resolve } from '$app/paths';
	import { FileText } from '@lucide/svelte';
	import type { BrowseSort } from '$lib/browse-sort';
	import { listBadge } from '$lib/collection-state';
	import type { CollectionRow } from '$lib/collections';
	import { identifierInCatalog } from '$lib/explorer';
	import { formatTimestamp, shortened, timestampAttribute } from '$lib/format';
	import Badge from './Badge.svelte';
	import BrowseTable from './BrowseTable.svelte';

	interface Props {
		label: string;
		collections: readonly CollectionRow[];
		sort: BrowseSort;
		prefix?: string;
	}

	let { label, collections, sort, prefix = '' }: Props = $props();
	const cell = 'border-r border-b border-app-line px-4 py-2 align-top last:border-r-0';
</script>

<BrowseTable {label} {sort} {prefix} countColumns={['Files']}>
	{#each collections as collection (collection.id)}
		{@const badge = listBadge(collection.state)}
		<tr class="hover:bg-app-hover">
			<th scope="row" class="{cell} font-normal">
				<div class="flex min-w-0 items-start gap-2">
					<FileText size={17} class="mt-0.5 shrink-0 text-app-muted" aria-hidden="true" />
					<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
						<a
							href={resolve('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]', {
								catalog: collection.catalog,
								identifier: identifierInCatalog(collection.identifier)
							})}
							title={collection.title !== collection.name ? collection.title : undefined}
							class="font-semibold wrap-anywhere text-app-fg no-underline hover:underline"
							>{collection.name}</a
						>
						{#if badge}<Badge tone={badge.tone}>{badge.label}</Badge>{/if}
					</div>
				</div>
			</th>
			<td class="{cell} text-right tabular-nums">{collection.fileCount}</td>
			<td class="{cell} wrap-anywhere">{shortened(collection.createdBy, 200)}</td>
			<td class="{cell} wrap-anywhere text-app-muted">
				<time datetime={timestampAttribute(collection.createdAt)}
					>{formatTimestamp(collection.createdAt)}</time
				>
			</td>
		</tr>
	{/each}
</BrowseTable>
