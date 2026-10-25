<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { Files } from '@lucide/svelte';
	import type { PolarisBrowseData, PolarisGenericTable } from '$api/types';
	import { datasetLayer, datasetTypeLabel } from '$api/catalog-datasets';
	import DatasetGovernance from './DatasetGovernance.svelte';

	let {
		data,
		table,
		href
	}: {
		data: PolarisBrowseData;
		table: PolarisGenericTable;
		href: (changes: Record<string, string | null>) => '/browse' | `/browse?${string}`;
	} = $props();
	const tabs = [
		{ id: 'overview', label: 'Overview' },
		{ id: 'files', label: 'Files' },
		{ id: 'history', label: 'History' },
		{ id: 'permissions', label: 'Permissions' },
		{ id: 'policies', label: 'Policies' },
		{ id: 'lineage', label: 'Lineage' }
	];
	const active = $derived(
		tabs.find((tab) => tab.id === page.url.searchParams.get('tab'))?.id ?? 'overview'
	);
	const layer = $derived(datasetLayer(data.selected.namespace, table.properties));
	const description = $derived(table.doc || table.properties.description || '');
</script>

<div class="min-w-0">
	<header class="flex min-w-0 flex-wrap items-center gap-3 border-b border-app-line px-4 py-3">
		<Files size={19} class="shrink-0 text-app-muted" />
		<h1 class="min-w-0 flex-1 break-all text-xl font-semibold tracking-normal">{table.name}</h1>
		<span
			class="shrink-0 rounded border border-app-line px-2 py-0.5 text-[10px] font-medium text-app-muted"
			>{datasetTypeLabel(table)}</span
		>
	</header>
	<nav
		aria-label="Dataset details"
		class="flex min-w-0 flex-wrap gap-x-5 border-b border-app-line px-4"
	>
		{#each tabs as tab (tab.id)}<a
				href={resolve(href({ tab: tab.id, branch: null, snapshot: null }))}
				aria-current={active === tab.id ? 'page' : undefined}
				class={[
					'border-b-2 py-3 text-xs font-medium',
					active === tab.id
						? 'border-brand-strong text-brand-strong'
						: 'border-transparent text-app-muted hover:text-app-fg'
				]}>{tab.label}</a
			>{/each}
	</nav>
	<div class="min-w-0 p-4 sm:p-5">
		{#if active === 'overview'}
			{#if description}<p class="mb-5 text-sm leading-6 text-app-fg">{description}</p>{/if}
			<dl class="grid gap-4 text-xs">
				<div>
					<dt class="mb-1 text-app-muted">Registered format</dt>
					<dd>{table.storageFormat}</dd>
				</div>
				<div>
					<dt class="mb-1 text-app-muted">Processing layer</dt>
					<dd class={layer.id === 'conflict' ? 'text-app-danger' : ''}>{layer.label}</dd>
					<dd class="mt-1 text-app-muted">{layer.detail}</dd>
				</div>
				<div>
					<dt class="mb-1 text-app-muted">Storage location</dt>
					<dd class="break-all font-mono">{table.location || 'No location recorded'}</dd>
				</div>
				<div>
					<dt class="mb-1 text-app-muted">Catalog registration</dt>
					<dd>Persisted in Polaris</dd>
				</div>
			</dl>
			<p class="mt-5 border-t border-app-line pt-4 text-xs leading-5 text-app-muted">
				This page shows the registered dataset metadata. Registration does not verify or upload the
				files at its storage location.
			</p>
			{#if Object.keys(table.properties).length}<details class="mt-5">
					<summary class="text-xs font-medium">Catalog properties</summary>
					<dl class="mt-3 grid gap-3 text-xs">
						{#each Object.entries(table.properties) as [name, value] (name)}<div
								class="grid min-w-0 gap-1 sm:grid-cols-[minmax(100px,1fr)_minmax(0,3fr)]"
							>
								<dt class="break-all text-app-muted">{name}</dt>
								<dd class="break-all font-mono">{value}</dd>
							</div>{/each}
					</dl>
				</details>{/if}
		{:else if active === 'permissions' || active === 'policies'}
			<DatasetGovernance
				governance={data.governance}
				catalog={data.selected.catalog}
				kind={active}
				{href}
			/>
		{:else if active === 'files'}
			<h2 class="m-0 border-0 p-0 text-sm font-semibold">Files and manifests</h2>
			<p class="mt-3 max-w-2xl text-sm leading-6 text-app-muted">
				File listing is not connected for this registration. Polaris stores the dataset’s location
				and properties; this view has no verified file manifest, sizes or checksums to display.
			</p>
			{#if table.location}<p class="mt-4 break-all font-mono text-xs">{table.location}</p>{/if}
		{:else if active === 'history'}
			<h2 class="m-0 border-0 p-0 text-sm font-semibold">Version history</h2>
			<p class="mt-3 max-w-2xl text-sm leading-6 text-app-muted">
				Version history is not connected to this generic catalog registration.
			</p>
		{:else}
			<h2 class="m-0 border-0 p-0 text-sm font-semibold">Lineage</h2>
			<p class="mt-3 max-w-2xl text-sm leading-6 text-app-muted">
				No version-specific scientific lineage is connected to this registration. Sharing a catalog
				or namespace with an Icechunk or Iceberg dataset does not establish an input relationship.
			</p>
		{/if}
	</div>
</div>
