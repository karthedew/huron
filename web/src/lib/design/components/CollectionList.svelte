<script lang="ts">
	import { resolve } from '$app/paths';
	import { FileText } from '@lucide/svelte';
	import { listBadge } from '$lib/collection-state';
	import type { CollectionRow } from '$lib/collections';
	import { identifierInCatalog } from '$lib/explorer';
	import { countLabel, formatTimestamp, timestampAttribute } from '$lib/format';
	import Badge from './Badge.svelte';

	interface Props {
		/** The list's name, e.g. "Collections". */
		label: string;
		collections: readonly CollectionRow[];
	}

	let { label, collections }: Props = $props();
</script>

<ul class="m-0 grid list-none gap-2 p-0" aria-label={label}>
	{#each collections as collection (collection.id)}
		{@const badge = listBadge(collection.state)}
		<!-- With room, the file count and the time stand on the right of the title. -->
		<li
			class="@container rounded-card border border-app-line bg-app-card px-4 py-3 hover:border-app-line-strong"
		>
			<div
				class="flex flex-col gap-1 @2xl:flex-row @2xl:items-start @2xl:justify-between @2xl:gap-4"
			>
				<div class="flex min-w-0 gap-3">
					<FileText size={18} class="mt-0.5 shrink-0 text-app-muted" aria-hidden="true" />
					<div class="min-w-0">
						<p class="m-0 flex flex-wrap items-center gap-x-2 gap-y-1">
							<a
								href={resolve('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]', {
									catalog: collection.catalog,
									identifier: identifierInCatalog(collection.identifier)
								})}
								class="font-semibold wrap-anywhere text-app-fg no-underline hover:underline"
								>{collection.title}</a
							>
							{#if badge}<Badge tone={badge.tone}>{badge.label}</Badge>{/if}
						</p>
						<p class="mono mt-1 mb-0 text-xs break-all text-app-muted">{collection.identifier}</p>
					</div>
				</div>
				<p
					class="m-0 flex flex-wrap gap-x-3 gap-y-0.5 pl-7.5 text-xs text-app-muted @2xl:shrink-0 @2xl:justify-end @2xl:pt-1 @2xl:pl-0"
				>
					<span>{countLabel(collection.fileCount, 'file')}</span>
					<span
						>Updated <time datetime={timestampAttribute(collection.updatedAt)}
							>{formatTimestamp(collection.updatedAt)}</time
						></span
					>
				</p>
			</div>
		</li>
	{/each}
</ul>
