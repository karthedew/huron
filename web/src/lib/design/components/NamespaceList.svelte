<script lang="ts">
	import { resolve } from '$app/paths';
	import { Folder } from '@lucide/svelte';
	import type { Namespace } from '$api/types';
	import type { BrowseSort } from '$lib/browse-sort';
	import { formatTimestamp, shortened, timestampAttribute } from '$lib/format';
	import BrowseTable from './BrowseTable.svelte';

	interface Props {
		label: string;
		namespaces: readonly Namespace[];
		sort: BrowseSort;
		prefix?: string;
	}

	let { label, namespaces, sort, prefix = '' }: Props = $props();
	const cell = 'border-r border-b border-app-line px-4 py-2 align-top last:border-r-0';
</script>

<BrowseTable {label} {sort} {prefix} countColumns={['Namespaces', 'Collections']}>
	{#each namespaces as namespace (namespace.id)}
		<tr class="hover:bg-app-hover">
			<th scope="row" class="{cell} font-normal">
				<div class="flex min-w-0 items-start gap-2">
					<Folder size={17} class="mt-0.5 shrink-0 text-brand-strong" aria-hidden="true" />
					<div class="min-w-0">
						<a
							href={resolve('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]', {
								catalog: namespace.catalog,
								path: namespace.path
							})}
							class="font-semibold wrap-anywhere text-app-fg no-underline hover:underline"
							>{namespace.name}</a
						>
					</div>
				</div>
			</th>
			<td class="{cell} text-right tabular-nums">{namespace.namespace_count}</td>
			<td class="{cell} text-right tabular-nums">{namespace.collection_count}</td>
			<td class="{cell} wrap-anywhere">{shortened(namespace.created_by, 200)}</td>
			<td class="{cell} wrap-anywhere text-app-muted">
				<time datetime={timestampAttribute(namespace.created_at)}
					>{formatTimestamp(namespace.created_at)}</time
				>
			</td>
		</tr>
	{/each}
</BrowseTable>
