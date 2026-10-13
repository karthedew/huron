<script lang="ts">
	import { Database, Folder, Files, ChevronRight, ArrowUp, Search } from '@lucide/svelte';
	import { untrack } from 'svelte';
	import { browseRawTargets } from '$api/client';
	import type { PolarisCatalog, RawTargetBranch } from '$api/types';
	let {
		catalogs,
		initialBranch,
		onloading,
		onchange
	}: {
		catalogs: PolarisCatalog[];
		initialBranch: RawTargetBranch | null;
		onloading: (loading: boolean) => void;
		onchange: (branch: RawTargetBranch, name: string) => void;
	} = $props();
	let branch = $state.raw(untrack(() => initialBranch));
	let search = $state('');
	let busy = $state(false);
	let failure = $state('');
	let requestId = 0;
	const term = $derived(search.trim().toLowerCase());
	async function open(catalog: string, namespace: string[], more = false) {
		const request = ++requestId;
		busy = true;
		onloading(true);
		failure = '';
		try {
			const next = await browseRawTargets(
				catalog,
				namespace,
				more ? branch?.nextNamespacePageToken : null,
				more ? branch?.nextDatasetPageToken : null
			);
			if (request !== requestId) return;
			branch =
				more && branch
					? {
							...next,
							nextNamespacePageToken: branch.nextNamespacePageToken
								? next.nextNamespacePageToken
								: null,
							nextDatasetPageToken: branch.nextDatasetPageToken ? next.nextDatasetPageToken : null,
							folders: [
								...new Map(
									[...branch.folders, ...next.folders].map((folder) => [
										JSON.stringify(folder),
										folder
									])
								).values()
							],
							datasets: [
								...new Map(
									[...branch.datasets, ...next.datasets].map((dataset) => [dataset.name, dataset])
								).values()
							]
						}
					: next;
			if (!more) {
				search = '';
				onchange(branch, '');
			}
		} catch (error) {
			if (request === requestId)
				failure = error instanceof Error ? error.message : 'Unable to load this folder.';
		} finally {
			if (request === requestId) {
				busy = false;
				onloading(false);
			}
		}
	}
</script>

<div class="overflow-hidden rounded-md border border-app-line bg-app-bg">
	<div class="border-b border-app-line p-3">
		<label class="flex items-center gap-2 text-app-muted"
			><Search size={15} /><span class="sr-only">Find catalogs, folders or datasets</span><input
				type="search"
				bind:value={search}
				class="min-w-0 flex-1 bg-transparent text-xs text-app-fg outline-none focus-visible:ring-2 focus-visible:ring-brand"
				placeholder="Find catalogs, folders or datasets"
			/></label
		>
	</div>
	<div class="grid min-w-0 sm:grid-cols-[minmax(130px,1fr)_minmax(0,2fr)]">
		<nav
			aria-label="Organization catalogs"
			class="min-w-0 border-b border-app-line p-2 sm:border-r sm:border-b-0"
		>
			{#each catalogs.filter((catalog) => !term || catalog.name
						.toLowerCase()
						.includes(term)) as catalog (catalog.name)}
				<button
					type="button"
					onclick={() => open(catalog.name, [])}
					class={[
						'flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs hover:bg-app-hover focus-visible:ring-2 focus-visible:ring-brand',
						branch?.catalog === catalog.name ? 'bg-brand-soft text-brand-strong' : 'text-app-fg'
					]}
					aria-current={branch?.catalog === catalog.name ? 'location' : undefined}
					><Database size={14} class="shrink-0" /><span class="min-w-0 break-all"
						>{catalog.name}</span
					></button
				>
			{:else}<p class="p-2 text-xs text-app-muted">No matching catalogs.</p>{/each}
		</nav>
		<div class="min-w-0 p-3" aria-busy={busy}>
			{#if branch}<div class="mb-3 flex min-w-0 items-start gap-2 border-b border-app-line pb-3">
					<button
						type="button"
						aria-label="Parent folder"
						disabled={busy || !branch.namespace.length}
						onclick={() => branch && open(branch.catalog, branch.namespace.slice(0, -1))}
						class="rounded p-1 text-app-muted hover:bg-app-hover disabled:opacity-30"
						><ArrowUp size={15} /></button
					>
					<p class="min-w-0 break-all text-xs leading-6 text-app-muted">
						{branch.catalog}{branch.namespace.length ? ' / ' + branch.namespace.join(' / ') : ''}
					</p>
				</div>
				{#each branch.folders.filter((folder) => !term || folder
							.at(-1)
							?.toLowerCase()
							.includes(term)) as folder (JSON.stringify(folder))}
					<button
						type="button"
						disabled={busy}
						onclick={() => branch && open(branch.catalog, folder)}
						class="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs hover:bg-app-hover"
						><Folder size={15} class="shrink-0 text-brand-strong" /><span
							class="min-w-0 flex-1 break-all">{folder.at(-1)}</span
						><ChevronRight size={14} /></button
					>
				{/each}
				{#each branch.datasets.filter((dataset) => !term || dataset.name
							.toLowerCase()
							.includes(term)) as dataset (dataset.name)}
					<button
						type="button"
						disabled={busy || !dataset.datasetId}
						onclick={() => branch && onchange(branch, dataset.name)}
						class="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs hover:bg-app-hover disabled:opacity-50"
						title={dataset.datasetId
							? 'Upload a revision'
							: 'External registration: upload is unavailable'}
						><Files size={15} class="shrink-0" /><span class="min-w-0 flex-1 break-all"
							>{dataset.name}</span
						><span class="text-[10px] text-app-muted">{dataset.datasetId ? 'Raw' : 'External'}</span
						></button
					>
				{/each}
				{#if !branch.folders.length && !branch.datasets.length}<p
						class="py-3 text-xs text-app-muted"
					>
						This folder is empty.
					</p>{/if}
				{#if branch.nextNamespacePageToken || branch.nextDatasetPageToken}<button
						type="button"
						disabled={busy}
						onclick={() => branch && open(branch.catalog, branch.namespace, true)}
						class="mt-3 text-xs text-brand-strong underline">Load more entries</button
					>{/if}
			{:else}<p class="py-4 text-xs text-app-muted">
					Select a catalog to browse its namespaces.
				</p>{/if}
			{#if busy}<p role="status" class="mt-3 text-xs text-app-muted">Loading folder…</p>{/if}
			{#if failure}<p role="alert" class="mt-3 text-xs text-app-danger">{failure}</p>{/if}
		</div>
	</div>
</div>
