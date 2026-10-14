<script lang="ts">
	import { resolve } from '$app/paths';
	import { ChevronRight, Database, Files, Folder, Search, Table2 } from '@lucide/svelte';
	import type { PolarisBrowseData } from '$api/types';
	import { datasetLayer, datasetTypeLabel } from '$api/catalog-datasets';
	import { browseHref } from '$lib/stores/workspace';
	import RepositoryPanel from './RepositoryPanel.svelte';
	import PolarisForm from './PolarisForm.svelte';
	let {
		data,
		organization,
		href
	}: {
		data: PolarisBrowseData;
		organization: string;
		href: (changes: Record<string, string | null>) => '/browse' | `/browse?${string}`;
	} = $props();
	let query = $state('');
	let typeFilter = $state('all');
	let layerFilter = $state('all');
	const folders = $derived(
		data.namespaces.filter((namespace) =>
			(namespace.at(-1) ?? '').toLocaleLowerCase().includes(query.toLocaleLowerCase())
		)
	);
	const datasets = $derived(
		[...data.tables, ...data.icebergTables, ...data.rawTables]
			.map((dataset) => ({
				dataset,
				layer: datasetLayer(
					dataset.namespace ?? data.selected.namespace,
					'properties' in dataset ? dataset.properties : undefined
				),
				type:
					dataset.format === 'raw' && dataset.isRaw !== true
						? 'generic'
						: (dataset.format ?? 'icechunk')
			}))
			.filter(
				({ dataset, type, layer }) =>
					dataset.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()) &&
					(typeFilter === 'all' || type === typeFilter) &&
					(layerFilter === 'all' || layer.id === layerFilter)
			)
			.sort((a, b) => a.dataset.name.localeCompare(b.dataset.name))
	);
	const filtering = $derived(!!query || typeFilter !== 'all' || layerFilter !== 'all');
	const listingUnavailable = $derived(
		data.errors.namespaces ||
			data.errors.tables ||
			data.errors.icebergTables ||
			data.errors.rawTables
	);
</script>

<div class="min-w-0">
	<div
		class="folder-filters flex flex-wrap items-center gap-2 border-b border-app-line px-4 py-2.5"
	>
		<label class="relative min-w-40 flex-1"
			><span class="visually-hidden">Filter folder contents</span><Search
				size={14}
				class="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-app-muted"
			/><input
				type="search"
				bind:value={query}
				placeholder="Filter names"
				class="folder-search w-full rounded border border-app-line bg-app-bg text-xs"
			/></label
		>
		<label
			><span class="visually-hidden">Dataset type</span><select
				bind:value={typeFilter}
				class="rounded border border-app-line bg-app-bg text-xs"
			>
				<option value="all">All types</option><option value="raw">Raw files</option><option
					value="icechunk">Icechunk</option
				><option value="iceberg">Iceberg</option><option value="generic">Generic</option>
			</select></label
		>
		<label
			><span class="visually-hidden">Processing layer</span><select
				bind:value={layerFilter}
				class="rounded border border-app-line bg-app-bg text-xs"
			>
				<option value="all">All layers</option><option value="bronze">Bronze</option><option
					value="silver">Silver</option
				><option value="gold">Gold</option><option value="unassigned">Unassigned</option><option
					value="unknown">Not loaded</option
				><option value="conflict">Layer conflict</option>
			</select></label
		>
	</div>
	<p class="px-4 py-2 text-xs text-app-muted" role="status">
		{datasets.length} datasets · {folders.length} folders on this page.
		{#if filtering}Type and layer filters apply to datasets; folders remain navigable.{/if}
	</p>
	<div class="min-w-0 overflow-x-auto" role="region" aria-label="Folder contents">
		<table class="m-0 w-full text-left text-xs">
			<thead
				><tr class="border-b border-app-line text-app-muted"
					><th class="px-4 py-2 font-medium">Name</th><th class="px-4 py-2 font-medium">Type</th><th
						class="px-4 py-2 font-medium">Layer</th
					></tr
				></thead
			>
			<tbody>
				{#each folders as namespace (JSON.stringify(namespace))}<tr
						class="border-b border-app-line/60 hover:bg-app-sidebar-hover/50"
					>
						<td class="px-4 py-2"
							><a
								href={resolve(browseHref(data.selected.catalog, namespace, '', organization))}
								class="inline-flex min-w-0 items-start gap-2 text-app-fg"
								><Folder size={15} class="mt-0.5 shrink-0 text-app-muted" /><span class="break-all"
									>{namespace.at(-1)}</span
								><ChevronRight size={13} class="mt-0.5 shrink-0 text-app-muted" /></a
							></td
						>
						<td class="whitespace-nowrap px-4 py-2 text-app-muted">Namespace</td><td
							class="px-4 py-2 text-app-muted">—</td
						>
					</tr>{/each}
				{#each datasets as { dataset, layer } (`${dataset.format ?? 'icechunk'}:${dataset.name}`)}<tr
						class="border-b border-app-line/60 hover:bg-app-sidebar-hover/50"
					>
						<td class="px-4 py-2"
							><a
								href={resolve(
									href({
										table: dataset.name,
										format: dataset.format === 'icechunk' ? null : (dataset.format ?? null),
										tab: null,
										branch: null,
										snapshot: null,
										policiesPageToken: null
									})
								)}
								class="inline-flex items-start gap-2 text-app-fg"
							>
								{#if dataset.format === 'raw'}<Files
										size={15}
										class="mt-0.5 shrink-0 text-app-muted"
									/>{:else if dataset.format === 'iceberg'}<Table2
										size={15}
										class="mt-0.5 shrink-0 text-app-muted"
									/>{:else}<Database size={15} class="mt-0.5 shrink-0 text-app-muted" />{/if}
								<span class="break-all">{dataset.name}</span></a
							></td
						>
						<td class="whitespace-nowrap px-4 py-2 text-app-muted">{datasetTypeLabel(dataset)}</td>
						<td class="whitespace-nowrap px-4 py-2 text-app-muted"
							><span title={layer.detail} class={layer.id === 'conflict' ? 'text-app-danger' : ''}
								>{layer.label}</span
							></td
						>
					</tr>{/each}
			</tbody>
		</table>
	</div>
	{#if !datasets.length}<p class="px-4 py-5 text-sm text-app-muted">
			{filtering
				? 'No datasets match these filters on this page.'
				: listingUnavailable
					? 'Some dataset listings are unavailable to this account.'
					: folders.length
						? 'Open a namespace folder to browse its datasets.'
						: 'This folder is empty.'}
		</p>{/if}
	{#if datasets.length && listingUnavailable}<p class="px-4 py-3 text-xs text-app-muted">
			Some dataset listings are unavailable to this account.
		</p>{/if}
	<div class="flex flex-wrap gap-4 px-4 py-2 text-xs">
		{#if data.nextNamespacePageToken}<a
				href={resolve(href({ namespacePageToken: data.nextNamespacePageToken, table: null }))}
				>Next folders →</a
			>{/if}
		{#if data.nextPageToken}<a href={resolve(href({ pageToken: data.nextPageToken, table: null }))}
				>Next Icechunk datasets →</a
			>{/if}
		{#if data.nextIcebergPageToken}<a
				href={resolve(href({ icebergPageToken: data.nextIcebergPageToken, table: null }))}
				>Next Iceberg tables →</a
			>{/if}
		{#if data.nextRawPageToken}<a
				href={resolve(href({ rawPageToken: data.nextRawPageToken, table: null }))}
				>Next file registrations →</a
			>{/if}
	</div>
	<p class="px-4 py-2 text-xs leading-5 text-app-muted">
		Layer comes from namespace placement or loaded <code>huron.layer</code> metadata. A dataset’s storage
		type does not determine its processing stage.
	</p>
	<details class="namespace-operations m-4 rounded border border-app-line bg-app-bg/40 p-3">
		<summary class="text-xs font-semibold">Namespace operations</summary>
		<div class="mt-4">
			<RepositoryPanel
				{data}
				table={null}
				{href}
				showCatalogSelector={false}
				showCatalogControls={false}
				showResourceNavigation={false}
			/>
		</div>
		{#if data.selected.namespace.length}
			<details class="mt-5 border-t border-app-line pt-4">
				<summary class="text-xs font-semibold">Register a Raw collection</summary>
				<div class="mt-4">
					<PolarisForm action="registerRawTable" submit="Register Raw collection">
						<input type="hidden" name="catalog" value={data.selected.catalog} />
						<input type="hidden" name="namespace" value={JSON.stringify(data.selected.namespace)} />
						<label>Dataset name<input name="name" required placeholder="source_files" /></label>
						<label
							>Storage location · optional<input
								name="location"
								placeholder="s3://science-data/source-files/"
							/></label
						>
						<label>Description · optional<textarea name="doc" rows="2"></textarea></label>
						<label
							>Processing layer<select name="layer"
								><option value="">Use namespace placement</option><option value="bronze"
									>Bronze</option
								><option value="silver">Silver</option><option value="gold">Gold</option></select
							></label
						>
						<label
							>Dataset properties · JSON<textarea name="properties" rows="3" value={'{}'}
							></textarea></label
						>
						<p class="text-xs leading-5 text-app-muted">
							Registers existing Raw collection metadata in Polaris. No files are uploaded, verified
							or published. Processing-layer metadata must agree with bronze, silver or gold
							namespace placement.
						</p>
					</PolarisForm>
				</div>
			</details>
			<details class="mt-5 border-t border-app-line pt-4">
				<summary class="text-xs font-semibold">Register an Iceberg table</summary>
				<div class="mt-4">
					<PolarisForm action="registerIcebergTable" submit="Register Iceberg table">
						<input type="hidden" name="catalog" value={data.selected.catalog} />
						<input type="hidden" name="namespace" value={JSON.stringify(data.selected.namespace)} />
						<label>Dataset name<input name="name" required placeholder="daily_statistics" /></label>
						<label
							>Existing metadata JSON location<input
								name="metadataLocation"
								required
								placeholder="s3://science-data/table/metadata/v1.metadata.json"
							/></label
						>
						<p class="text-xs leading-5 text-app-muted">
							Registers an existing Iceberg metadata file through Polaris. The metadata and data
							files must already exist and be accessible to Polaris. This does not create or upload
							table data.
						</p>
					</PolarisForm>
				</div>
			</details>
		{/if}
	</details>
</div>

<style>
	.folder-filters input.folder-search[type='search'],
	.folder-filters select {
		height: 2rem;
		padding: 0.25rem 0.5rem;
		font-size: 0.75rem;
	}
	.folder-filters input.folder-search[type='search'] {
		padding-left: 1.75rem;
	}
	.namespace-operations :global(.panel) {
		border: 0;
		border-radius: 0;
		padding: 0;
		background: transparent;
	}
	.namespace-operations :global(.section-heading h2) {
		font-size: 0.85rem;
	}
</style>
