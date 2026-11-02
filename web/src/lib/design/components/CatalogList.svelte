<script lang="ts">
	import { resolve } from '$app/paths';
	import { Database } from '@lucide/svelte';
	import type { Catalog } from '$api/types';
	import type { BrowseSort } from '$lib/browse-sort';
	import { formatTimestamp, shortened, timestampAttribute } from '$lib/format';
	import BrowseTable from './BrowseTable.svelte';

	interface Props {
		catalogs: readonly Catalog[];
		sort: BrowseSort;
	}

	let { catalogs, sort }: Props = $props();
	const cell = 'border-r border-b border-app-line px-4 py-2 align-top last:border-r-0';
</script>

<BrowseTable label="Catalogs" {sort} countColumns={['Namespaces']}>
	{#each catalogs as catalog (catalog.id)}
		<tr class="hover:bg-app-hover">
			<th scope="row" class="{cell} font-normal">
				<div class="flex min-w-0 items-start gap-2">
					<Database size={17} class="mt-0.5 shrink-0 text-brand-strong" aria-hidden="true" />
					<div class="min-w-0">
						<a
							href={resolve('/(app)/catalogs/[catalog=segment]', { catalog: catalog.name })}
							title={catalog.display_name && catalog.display_name !== catalog.name
								? catalog.display_name
								: undefined}
							class="font-semibold wrap-anywhere text-app-fg no-underline hover:underline"
							>{catalog.name}</a
						>
					</div>
				</div>
			</th>
			<td class="{cell} text-right tabular-nums">{catalog.namespace_count}</td>
			<td class="{cell} wrap-anywhere">{shortened(catalog.created_by, 200)}</td>
			<td class="{cell} wrap-anywhere text-app-muted">
				<time datetime={timestampAttribute(catalog.created_at)}
					>{formatTimestamp(catalog.created_at)}</time
				>
			</td>
		</tr>
	{/each}
</BrowseTable>
