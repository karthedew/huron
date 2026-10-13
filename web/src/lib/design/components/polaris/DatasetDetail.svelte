<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { Database, GitBranch, Table2, TableProperties } from '@lucide/svelte';
	import type {
		IcechunkInspection,
		PolarisBrowseData,
		PolarisIcechunkTable,
		PolarisIcebergTable,
		PolarisIcebergFieldType,
		PolarisDatasetTab
	} from '$api/types';
	import { datasetLayer } from '$api/catalog-datasets';
	import RepositoryOperations from './RepositoryOperations.svelte';
	import DatasetGovernance from './DatasetGovernance.svelte';
	let {
		data,
		table,
		inspection,
		href
	}: {
		data: PolarisBrowseData;
		table: PolarisIcechunkTable | PolarisIcebergTable;
		inspection: IcechunkInspection | null;
		href: (changes: Record<string, string | null>) => '/browse' | `/browse?${string}`;
	} = $props();
	const tabs: { id: PolarisDatasetTab; label: string }[] = [
		{ id: 'overview', label: 'Overview' },
		{ id: 'schema', label: 'Schema' },
		{ id: 'history', label: 'History' },
		{ id: 'permissions', label: 'Permissions' },
		{ id: 'policies', label: 'Policies' },
		{ id: 'lineage', label: 'Lineage' }
	];
	const active = $derived(
		tabs.find((tab) => tab.id === page.url.searchParams.get('tab'))?.id ?? 'overview'
	);
	const iceberg = $derived(table.format === 'iceberg' ? table : null);
	const nativeSnapshot = $derived(
		iceberg?.snapshots.find(
			(snapshot) =>
				snapshot.snapshotId ===
				(page.url.searchParams.get('snapshot') ||
					iceberg.refs[page.url.searchParams.get('branch') ?? '']?.snapshotId ||
					iceberg.currentSnapshotId)
		) ?? null
	);
	const nativeSchema = $derived(
		iceberg?.schemas.find(
			(schema) =>
				schema.schemaId ===
				(nativeSnapshot?.schemaId ??
					(!nativeSnapshot || nativeSnapshot.snapshotId === iceberg.currentSnapshotId
						? iceberg.currentSchemaId
						: -1))
		) ?? null
	);
	const repositoryBranches = $derived(
		iceberg
			? Object.entries(iceberg.refs)
					.filter(([, ref]) => ref.type === 'branch')
					.map(([name, ref]) => ({ name, snapshotId: ref.snapshotId }))
			: (inspection?.branches ?? [])
	);
	const selectedBranch = $derived(
		page.url.searchParams.get('branch') ??
			inspection?.selectedBranch ??
			(repositoryBranches.some((branch) => branch.name === 'main')
				? 'main'
				: (repositoryBranches[0]?.name ?? ''))
	);
	const available = $derived(inspection?.state === 'available');
	const description = $derived(table.properties.description ?? '');
	const layer = $derived(datasetLayer(data.selected.namespace, table.properties));
	function timestamp(value: string) {
		const parsed = new Date(value);
		return Number.isFinite(parsed.getTime())
			? `${parsed.toISOString().slice(0, 19).replace('T', ' ')} UTC`
			: value;
	}
	function attribute(value: unknown): string {
		return typeof value === 'string' ? value : (JSON.stringify(value) ?? '—');
	}
	function fieldType(type: PolarisIcebergFieldType): string {
		if (typeof type === 'string') return type;
		if (type.type === 'list') return `list<${fieldType(type.element)}>`;
		if (type.type === 'map') return `map<${fieldType(type.key)}, ${fieldType(type.value)}>`;
		return `struct<${type.fields.map((field) => `${field.name}: ${fieldType(field.type)}`).join(', ')}>`;
	}
	function sourceUrl(value: unknown): string | null {
		if (typeof value !== 'string') return null;
		try {
			const url = new URL(value);
			return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
		} catch {
			return null;
		}
	}
	const recordedSourceUrl = $derived(
		sourceUrl(
			inspection?.provenance?.source.url ??
				inspection?.provenance?.source.source_url ??
				inspection?.provenance?.source.source_uri
		)
	);
</script>

<div class="dataset-detail min-w-0">
	<div class="flex min-w-0 flex-wrap items-center gap-3 border-b border-app-line px-4 py-3">
		<div class="flex min-w-0 flex-1 basis-80 items-center gap-3">
			{#if iceberg}<Table2 size={19} class="shrink-0 text-app-muted" />{:else}<Database
					size={19}
					class="shrink-0 text-app-muted"
				/>{/if}
			<h1 class="min-w-0 flex-1 break-all text-xl font-semibold tracking-normal">{table.name}</h1>
			<span
				class="shrink-0 rounded border border-app-line px-2 py-0.5 text-[10px] font-medium text-app-muted"
				>{iceberg ? 'Iceberg' : 'Icechunk'}</span
			>
		</div>
		{#if repositoryBranches.length}
			<form
				method="GET"
				action={resolve('/browse')}
				class="dataset-branch ml-auto flex shrink-0 items-center gap-2"
			>
				<input type="hidden" name="catalog" value={data.selected.catalog} /><input
					type="hidden"
					name="namespace"
					value={JSON.stringify(data.selected.namespace)}
				/><input type="hidden" name="table" value={table.name} /><input
					type="hidden"
					name="tab"
					value={active}
				/>
				{#if iceberg}<input type="hidden" name="format" value="iceberg" />{/if}
				{#each ['organization', 'namespacePageToken', 'pageToken', 'icebergPageToken', 'rawPageToken', 'policiesPageToken'] as key (key)}{@const value =
						page.url.searchParams.get(key)}{#if value}<input
							type="hidden"
							name={key}
							{value}
						/>{/if}{/each}
				<GitBranch size={14} class="text-app-muted" /><label
					><span class="visually-hidden">Repository branch</span><select
						name="branch"
						value={selectedBranch}
						class="h-8 max-w-40 rounded border border-app-line bg-app-bg px-2 text-xs"
						>{#each repositoryBranches as branch (branch.name)}<option value={branch.name}
								>{branch.name}</option
							>{/each}</select
					></label
				><button
					type="submit"
					class="h-8 rounded border border-app-line px-2 text-xs text-app-muted">Open branch</button
				>
			</form>
		{/if}
	</div>
	<nav
		aria-label="Dataset details"
		class="flex min-w-0 overflow-x-auto border-b border-app-line px-4"
	>
		{#each tabs as tab (tab.id)}<a
				href={resolve(href({ tab: tab.id }))}
				aria-current={active === tab.id ? 'page' : undefined}
				class={[
					'shrink-0 border-b-2 px-3 py-2.5 text-xs font-medium',
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
					<dt class="mb-1 text-app-muted">Processing layer</dt>
					<dd class={layer.id === 'conflict' ? 'text-app-danger' : ''}>{layer.label}</dd>
					<dd class="mt-1 text-app-muted">{layer.detail}</dd>
				</div>
				<div>
					<dt class="mb-1 text-app-muted">Storage location</dt>
					<dd class="break-all font-mono">{table.location}</dd>
				</div>
				{#if iceberg && nativeSnapshot}<div>
						<dt class="mb-1 text-app-muted">Current snapshot</dt>
						<dd class="break-all font-mono">{nativeSnapshot.snapshotId}</dd>
					</div>
					<div>
						<dt class="mb-1 text-app-muted">Commit</dt>
						<dd>
							{nativeSnapshot.summary.operation ?? 'Snapshot'} · {timestamp(
								new Date(nativeSnapshot.timestampMs).toISOString()
							)}
						</dd>
					</div>
				{:else if available && inspection?.snapshot}<div>
						<dt class="mb-1 text-app-muted">Current snapshot</dt>
						<dd class="break-all font-mono">{inspection.snapshot.id}</dd>
					</div>
					<div>
						<dt class="mb-1 text-app-muted">Commit</dt>
						<dd>{inspection.snapshot.message} · {timestamp(inspection.snapshot.writtenAt)}</dd>
					</div>{/if}
			</dl>
			{#if available && inspection}<div
					class="mt-5 flex flex-wrap gap-5 border-y border-app-line py-3 text-xs text-app-muted"
				>
					<span><strong class="text-app-fg">{inspection.arrays.length}</strong> arrays</span><span
						><strong class="text-app-fg">{inspection.groups.length}</strong> groups</span
					><span><strong class="text-app-fg">{inspection.branches.length}</strong> branches</span>
				</div>{/if}
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
			{#if inspection?.provenance}<details class="mt-5">
					<summary class="text-xs font-medium">Source provenance</summary>
					<pre class="mt-3 overflow-x-auto text-xs"><code
							>{JSON.stringify(inspection.provenance, null, 2)}</code
						></pre>
				</details>{/if}
			{#if iceberg || available}
				<details class="mt-5">
					<summary class="text-xs font-medium">Branches and tags</summary>
					<ul class="mt-3 grid list-none gap-2 p-0 text-xs">
						{#if iceberg}{#each Object.entries(iceberg.refs) as [name, reference] (name)}<li
									class="flex flex-wrap gap-2"
								>
									<span>{reference.type}: {name}</span><a
										class="break-all font-mono"
										href={resolve(href({ snapshot: reference.snapshotId, tab: 'schema' }))}
										>{reference.snapshotId}</a
									>
								</li>{/each}
						{:else if inspection}{#each inspection.branches as branch (branch.name)}<li
									class="flex flex-wrap gap-2"
								>
									<span>branch: {branch.name}</span><a
										class="break-all font-mono"
										href={resolve(href({ snapshot: branch.snapshotId, tab: 'schema' }))}
										>{branch.snapshotId}</a
									>
								</li>{/each}{#each inspection.tags as tag (tag.name)}<li
									class="flex flex-wrap gap-2"
								>
									<span>tag: {tag.name}</span><a
										class="break-all font-mono"
										href={resolve(href({ snapshot: tag.snapshotId, tab: 'schema' }))}
										>{tag.snapshotId}</a
									>
								</li>{/each}{/if}
					</ul>
				</details>
			{/if}
			{#if !iceberg && !available}<p class="mt-5 text-xs leading-5 text-app-muted">
					{inspection?.message ?? 'Repository metadata inspection is unavailable.'}
				</p>{/if}
			{#if table.format !== 'iceberg'}<details class="mt-6 border-t border-app-line pt-4">
					<summary class="text-xs font-medium">Repository operations</summary>
					<div class="mt-4"><RepositoryOperations {data} {table} {inspection} /></div>
				</details>{/if}
		{:else if active === 'schema'}
			<h2 class="detail-heading">
				<TableProperties size={15} />
				{iceberg ? 'Table schema' : 'Array schema'}
			</h2>
			{#if iceberg && nativeSchema}
				<p class="mt-3 text-xs text-app-muted">Schema {nativeSchema.schemaId}</p>
				<div class="mt-4 min-w-0 overflow-x-auto" role="region" aria-label="Table schema">
					<table class="m-0 w-full text-left text-xs">
						<thead
							><tr class="border-b border-app-line text-app-muted"
								><th class="px-3 py-2 font-medium">Field</th><th class="px-3 py-2 font-medium"
									>Type</th
								><th class="px-3 py-2 font-medium">Required</th><th class="px-3 py-2 font-medium"
									>Description</th
								></tr
							></thead
						><tbody
							>{#each nativeSchema.fields as field (field.id)}<tr
									class="border-b border-app-line/60"
									><td class="px-3 py-2 font-mono"
										><details>
											<summary class="whitespace-nowrap text-xs">{field.name}</summary>
											<p class="mt-2 text-xs text-app-muted">Field ID: {field.id}</p>
										</details></td
									><td class="max-w-sm break-words px-3 py-2 font-mono">{fieldType(field.type)}</td
									><td class="px-3 py-2">{field.required ? 'Yes' : 'No'}</td><td
										class="px-3 py-2 text-app-muted">{field.doc ?? '—'}</td
									></tr
								>{/each}</tbody
						>
					</table>
				</div>
			{:else if available && inspection}
				<div class="mt-4 min-w-0 overflow-x-auto" role="region" aria-label="Array schema">
					<table class="m-0 w-full text-left text-xs">
						<thead
							><tr class="border-b border-app-line text-app-muted"
								><th class="px-3 py-2 font-medium">Array</th><th class="px-3 py-2 font-medium"
									>Data type</th
								><th class="px-3 py-2 font-medium">Dimensions</th><th class="px-3 py-2 font-medium"
									>Shape</th
								><th class="px-3 py-2 font-medium">Chunks</th><th class="px-3 py-2 font-medium"
									>Units</th
								></tr
							></thead
						><tbody
							>{#each inspection.arrays as array (array.path)}<tr
									class="border-b border-app-line/60"
									><td class="px-3 py-2.5 font-mono"
										><details>
											<summary class="whitespace-nowrap text-xs">{array.path}</summary>
											<dl class="mt-3 grid gap-2">
												{#each Object.entries(array.attributes) as [name, value] (name)}<div>
														<dt class="text-app-muted">{name}</dt>
														<dd class="break-all">{attribute(value)}</dd>
													</div>{:else}<div class="text-app-muted">No array attributes.</div>{/each}
											</dl>
										</details></td
									><td class="px-3 py-2.5 font-mono">{array.dtype}</td><td class="px-3 py-2.5"
										>{array.dimensions.map((name) => name ?? 'unnamed').join(' × ') || 'scalar'}</td
									><td class="px-3 py-2.5 font-mono">{array.shape.join(' × ') || 'scalar'}</td><td
										class="px-3 py-2.5 font-mono">{array.chunks.join(' × ') || 'scalar'}</td
									><td class="px-3 py-2.5">{attribute(array.attributes.units ?? '—')}</td></tr
								>{:else}<tr
									><td colspan="6" class="px-3 py-6 text-app-muted">No arrays in this snapshot.</td
									></tr
								>{/each}</tbody
						>
					</table>
				</div>
				{#if inspection.groups.length}<details class="mt-5">
						<summary class="text-xs font-medium">Group attributes</summary>
						<div class="mt-3 grid gap-4">
							{#each inspection.groups as group (group.path)}<div>
									<h3 class="m-0 text-xs font-semibold">{group.path || '/'}</h3>
									<pre class="mt-2 overflow-x-auto text-xs"><code
											>{JSON.stringify(group.attributes, null, 2)}</code
										></pre>
								</div>{/each}
						</div>
					</details>{/if}
			{:else}<p class="mt-4 text-sm text-app-muted">
					{iceberg
						? 'Schema identity is unavailable for this snapshot.'
						: (inspection?.message ?? 'Array schema is unavailable for this repository.')}
				</p>{/if}
		{:else if active === 'history'}
			<h2 class="detail-heading">Snapshot history</h2>
			{#if iceberg}<ol class="mt-4 grid list-none gap-0 p-0">
					{#each [...iceberg.snapshots].sort((a, b) => b.timestampMs - a.timestampMs) as snapshot (snapshot.snapshotId)}<li
							class="border-b border-app-line py-4"
						>
							<div class="flex flex-wrap justify-between gap-2">
								<strong class="text-sm font-medium"
									>{snapshot.summary.operation ?? 'Snapshot'}</strong
								><time class="text-xs text-app-muted"
									>{timestamp(new Date(snapshot.timestampMs).toISOString())}</time
								>
							</div>
							<a
								href={resolve(href({ snapshot: snapshot.snapshotId, tab: 'schema' }))}
								class="mt-2 block break-all font-mono text-xs">{snapshot.snapshotId}</a
							>
							<details class="mt-2">
								<summary class="text-xs text-app-muted">Snapshot summary</summary>
								<pre class="mt-2 overflow-x-auto text-xs"><code
										>{JSON.stringify(snapshot.summary, null, 2)}</code
									></pre>
							</details>
						</li>{:else}<li class="py-6 text-sm text-app-muted">No snapshots recorded.</li>{/each}
				</ol>
			{:else if available && inspection}<ol class="mt-4 grid list-none gap-0 p-0">
					{#each inspection.history as snapshot (snapshot.id)}<li
							class="border-b border-app-line py-4"
						>
							<div class="flex flex-wrap items-start justify-between gap-2">
								<strong class="text-sm font-medium"
									>{snapshot.message || 'No commit message'}</strong
								><time datetime={snapshot.writtenAt} class="text-xs text-app-muted"
									>{timestamp(snapshot.writtenAt)}</time
								>
							</div>
							<a
								href={resolve(href({ snapshot: snapshot.id, tab: 'schema' }))}
								class="mt-2 block break-all font-mono text-xs">{snapshot.id}</a
							>
							{#if snapshot.parentId}<p class="mt-1 break-all font-mono text-[10px] text-app-muted">
									Parent: {snapshot.parentId}
								</p>{/if}
						</li>{:else}<li class="py-6 text-sm text-app-muted">
							No snapshots are available on this branch.
						</li>{/each}
				</ol>{:else}<p class="mt-4 text-sm text-app-muted">
					{inspection?.message ?? 'Snapshot history is unavailable for this repository.'}
				</p>{/if}
			{#if inspection?.historyNextSnapshotId}<a
					href={resolve(href({ snapshot: inspection.historyNextSnapshotId, tab: 'history' }))}
					class="mt-4 block text-xs">Older snapshots →</a
				>{/if}
		{:else if active === 'permissions'}
			<DatasetGovernance
				governance={data.governance}
				catalog={data.selected.catalog}
				kind="permissions"
				{href}
			/>
		{:else if active === 'policies'}
			<DatasetGovernance
				governance={data.governance}
				catalog={data.selected.catalog}
				kind="policies"
				{href}
			/>
		{:else}
			<h2 class="detail-heading">Lineage</h2>
			{#if inspection?.provenance && inspection.snapshot}
				<div
					class="mt-4 grid items-center gap-3 text-xs sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]"
				>
					<div class="min-w-0 rounded border border-app-line p-3">
						<strong>Recorded source</strong>{#if recordedSourceUrl}<a
								class="mt-2 block break-all"
								href={recordedSourceUrl}
								target="_blank"
								rel="noreferrer">{recordedSourceUrl}</a
							>{/if}
					</div>
					<span class="text-app-muted" aria-hidden="true">→</span>
					<div class="min-w-0 rounded border border-app-line p-3">
						<strong>{table.name}</strong>
						<p class="mt-2 break-all font-mono">{inspection.snapshot.id}</p>
					</div>
				</div>
				<h3 class="mb-2 mt-5 text-xs font-semibold">Recorded provenance</h3>
				<pre class="overflow-x-auto text-xs"><code
						>{JSON.stringify(inspection.provenance.source, null, 2)}</code
					></pre>
				{#if inspection.provenance.importReceipt}<details class="mt-3">
						<summary class="text-xs font-medium">Import receipt, selections and checksums</summary>
						<pre class="mt-2 overflow-x-auto text-xs"><code
								>{JSON.stringify(inspection.provenance.importReceipt, null, 2)}</code
							></pre>
					</details>{/if}
			{/if}
			<p class="mt-4 text-sm leading-6 text-app-muted">
				{inspection?.lineage.message ??
					'Scientific lineage is not recorded by this catalog. Snapshot parents and import provenance are available in History and Overview.'}
			</p>
		{/if}
		{#if inspection?.truncated}<p class="mt-5 text-xs text-app-muted">
				This metadata view is bounded. Additional schema entries or history may exist.
			</p>{/if}
	</div>
</div>

<style>
	.dataset-detail :global(summary) {
		font-size: 0.75rem;
		font-weight: 500;
	}
	.dataset-branch label {
		display: block;
	}
	.dataset-branch select {
		height: 2rem;
		width: auto;
		max-width: 10rem;
		padding: 0.25rem 0.5rem;
		font-size: 0.75rem;
	}
	.dataset-branch label span {
		font-size: 0.75rem;
	}
	.detail-heading {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin: 0;
		padding: 0;
		border: 0;
		font-size: 0.85rem;
		font-weight: 600;
	}
</style>
