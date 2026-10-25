<script lang="ts">
	import { afterNavigate, goto } from '$app/navigation';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import {
		ChevronDown,
		ChevronRight,
		Database,
		Files,
		Folder,
		FolderOpen,
		Table2
	} from '@lucide/svelte';
	import type {
		HuronOrganizationSummary,
		PolarisBrowseBranch,
		PolarisBrowseData
	} from '$api/types';
	import { datasetTypeLabel } from '$api/catalog-datasets';
	import { branchFolders, browseHref } from '$lib/stores/workspace';

	let {
		data,
		organization
	}: { data: PolarisBrowseData; organization: HuronOrganizationSummary | null } = $props();
	let rememberedBranches = $state.raw<PolarisBrowseBranch[]>([]);
	let openedFolders = $state<string[]>([]);
	let collapsedFolders = $state<string[]>([]);
	let catalogExpanded = $state(true);

	let previousNamespace: string | undefined;
	const selectedKey = $derived(JSON.stringify(data.selected.namespace));
	const branches = $derived.by(() => {
		const result = new Map(
			rememberedBranches.map((branch) => [JSON.stringify(branch.namespace), branch])
		);
		for (const branch of data.branches) result.set(JSON.stringify(branch.namespace), branch);
		return result;
	});
	const expanded = $derived(
		new Set(
			[
				...openedFolders,
				...data.selected.namespace.map((_, index) =>
					JSON.stringify(data.selected.namespace.slice(0, index + 1))
				)
			].filter((key) => !collapsedFolders.includes(key))
		)
	);

	afterNavigate(() => {
		rememberedBranches = [...branches.values()];
		if (previousNamespace !== selectedKey) revealFolder(data.selected.namespace);
		previousNamespace = selectedKey;
	});

	function revealFolder(namespace: string[]) {
		const ancestors = namespace.map((_, index) => JSON.stringify(namespace.slice(0, index + 1)));
		collapsedFolders = collapsedFolders.filter((key) => !ancestors.includes(key));
		openedFolders = [...new Set([...openedFolders, ...ancestors])];
	}

	async function toggleFolder(namespace: string[]) {
		const key = JSON.stringify(namespace);
		if (expanded.has(key)) {
			collapsedFolders = [...collapsedFolders, key];
			return;
		}
		revealFolder(namespace);
		if (!branches.has(key))
			await goto(resolve(browseHref(data.selected.catalog, namespace, '', organization?.slug)), {
				noScroll: true,
				keepFocus: true
			});
	}

	function leafHref(
		namespace: string[],
		table: string,
		format = 'icechunk'
	): '/browse' | `/browse?${string}` {
		const query =
			JSON.stringify(namespace) === selectedKey
				? new URLSearchParams(page.url.searchParams)
				: new URLSearchParams();
		for (const key of [...query.keys()]) if (key.startsWith('/')) query.delete(key);
		if (
			table !== data.selected.table ||
			format !== (page.url.searchParams.get('format') ?? 'icechunk')
		) {
			query.delete('branch');
			query.delete('snapshot');
			query.delete('policyPageToken');
			query.delete('policiesPageToken');
		}
		query.set('catalog', data.selected.catalog);
		if (organization) query.set('organization', organization.slug);
		query.set('namespace', JSON.stringify(namespace));
		query.set('table', table);
		if (format !== 'icechunk') query.set('format', format);
		else query.delete('format');
		return `/browse?${query}`;
	}

	function paginationHref(
		branch: PolarisBrowseBranch,
		kind: 'namespacePageToken' | 'pageToken' | 'icebergPageToken' | 'genericPageToken',
		token: string | null
	): '/browse' | `/browse?${string}` {
		const query = new URLSearchParams({ catalog: data.selected.catalog });
		if (organization) query.set('organization', organization.slug);
		if (branch.namespace.length) query.set('namespace', JSON.stringify(branch.namespace));
		if (branch.namespacePageToken) query.set('namespacePageToken', branch.namespacePageToken);
		if (branch.repositoryPageToken) query.set('pageToken', branch.repositoryPageToken);
		if (branch.icebergPageToken) query.set('icebergPageToken', branch.icebergPageToken);
		if (branch.genericPageToken) query.set('genericPageToken', branch.genericPageToken);
		if (token) query.set(kind, token);
		else query.delete(kind);
		return `/browse?${query}`;
	}
</script>

{#snippet branchContents(namespace: string[], depth: number)}
	{@const branch = branches.get(JSON.stringify(namespace))}
	{#if branch}
		{@const folders = branchFolders(branch, data.selected.namespace)}
		<ul class="m-0 grid list-none gap-0 p-0">
			{#each folders as folder (JSON.stringify(folder))}
				{@const key = JSON.stringify(folder)}
				{@const isExpanded = expanded.has(key)}
				<li class="min-w-0">
					<div
						style:--tree-depth={depth}
						class={[
							'folder-row flex min-w-0 items-start gap-1 rounded pr-2 text-xs',
							selectedKey === key && !data.selected.table
								? 'bg-brand-soft font-semibold text-brand-strong'
								: 'text-app-fg hover:bg-app-sidebar-hover'
						]}
					>
						<button
							type="button"
							onclick={() => toggleFolder(folder)}
							aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${folder.join(' / ')}`}
							aria-expanded={isExpanded}
							class="mt-0.5 grid size-6 shrink-0 place-items-center rounded text-app-muted hover:text-app-fg"
							>{#if isExpanded}<ChevronDown size={14} />{:else}<ChevronRight
									size={14}
								/>{/if}</button
						>
						<a
							href={resolve(browseHref(data.selected.catalog, folder, '', organization?.slug))}
							onclick={() => revealFolder(folder)}
							aria-current={selectedKey === key && !data.selected.table ? 'page' : undefined}
							class="flex min-w-0 flex-1 items-start gap-1.5 py-1 text-inherit"
							title={folder.join(' / ')}
						>
							{#if isExpanded}<FolderOpen
									size={14}
									class="mt-0.5 shrink-0 text-brand-strong"
								/>{:else}<Folder size={14} class="mt-0.5 shrink-0 text-brand-strong" />{/if}
							<span class="min-w-0 break-all">{folder.at(-1)}</span>
						</a>
					</div>
					{#if isExpanded}{@render branchContents(folder, depth + 1)}{/if}
				</li>
			{/each}
			{#each branch.repositories as repository (`${repository.format ?? 'icechunk'}:${repository.name}`)}
				{@const typeId = `dataset-type-${encodeURIComponent(JSON.stringify([namespace, repository.name, repository.format ?? 'icechunk']))}`}
				<li class="min-w-0">
					<a
						style:--tree-depth={depth}
						href={resolve(leafHref(namespace, repository.name, repository.format ?? 'icechunk'))}
						aria-label={repository.name}
						aria-describedby={typeId}
						aria-current={selectedKey === JSON.stringify(namespace) &&
						data.selected.table === repository.name &&
						(repository.format ?? 'icechunk') ===
							(page.url.searchParams.get('format') ?? 'icechunk')
							? 'page'
							: undefined}
						class={[
							'repository-row flex min-w-0 items-start gap-2 rounded py-1 pr-2 text-xs',
							selectedKey === JSON.stringify(namespace) &&
							data.selected.table === repository.name &&
							(repository.format ?? 'icechunk') ===
								(page.url.searchParams.get('format') ?? 'icechunk')
								? 'bg-brand-soft font-semibold text-brand-strong'
								: 'text-app-fg hover:bg-app-sidebar-hover'
						]}
					>
						{#if repository.format === 'generic'}<Files
								size={14}
								class="mt-0.5 shrink-0 text-brand-strong"
							/>{:else if repository.format === 'iceberg'}<Table2
								size={14}
								class="mt-0.5 shrink-0 text-brand-strong"
							/>{:else}<Database size={14} class="mt-0.5 shrink-0 text-brand-strong" />{/if}<span
							class="min-w-0 flex-1 break-all">{repository.name}</span
						><span id={typeId} class="mt-0.5 shrink-0 text-[9px] font-normal text-app-muted"
							>{datasetTypeLabel(repository)}</span
						>
					</a>
				</li>
			{/each}
		</ul>
		{#if branch.errors.namespaces || branch.errors.tables || branch.errors.icebergTables || branch.errors.genericTables}<p
				style:--tree-depth={depth}
				class="folder-row py-2 pr-2 text-xs text-app-muted"
			>
				Some folder contents are unavailable.
			</p>
		{:else if !folders.length && !branch.repositories.length}<p
				style:--tree-depth={depth}
				class="folder-row py-2 pr-2 text-xs text-app-muted"
			>
				Empty folder
			</p>{/if}
		{#if branch.nextNamespacePageToken}<a
				href={resolve(paginationHref(branch, 'namespacePageToken', branch.nextNamespacePageToken))}
				class="block px-3 py-1 text-xs">Next folders →</a
			>{/if}
		{#if branch.namespacePageToken}<a
				href={resolve(paginationHref(branch, 'namespacePageToken', null))}
				class="block px-3 py-1 text-xs">First folder page</a
			>{/if}
		{#if branch.nextRepositoryPageToken}<a
				href={resolve(paginationHref(branch, 'pageToken', branch.nextRepositoryPageToken))}
				class="block px-3 py-1 text-xs">Next repositories →</a
			>{/if}
		{#if branch.repositoryPageToken}<a
				href={resolve(paginationHref(branch, 'pageToken', null))}
				class="block px-3 py-1 text-xs">First repository page</a
			>{/if}
		{#if branch.nextGenericPageToken}<a
				href={resolve(paginationHref(branch, 'genericPageToken', branch.nextGenericPageToken))}
				class="block px-3 py-1 text-xs">Next file registrations →</a
			>{/if}
		{#if branch.genericPageToken}<a
				href={resolve(paginationHref(branch, 'genericPageToken', null))}
				class="block px-3 py-1 text-xs">First file registration page</a
			>{/if}
		{#if branch.nextIcebergPageToken}<a
				href={resolve(paginationHref(branch, 'icebergPageToken', branch.nextIcebergPageToken))}
				class="block px-3 py-1 text-xs">Next Iceberg tables →</a
			>{/if}
		{#if branch.icebergPageToken}<a
				href={resolve(paginationHref(branch, 'icebergPageToken', null))}
				class="block px-3 py-1 text-xs">First Iceberg page</a
			>{/if}
	{/if}
{/snippet}

<section
	class="flex min-h-0 min-w-0 flex-1 flex-col border-b border-app-line bg-app-sidebar/35 md:border-b-0 md:border-r"
	aria-labelledby="explorer-heading"
>
	<div class="flex h-10 shrink-0 items-center border-b border-app-line px-3">
		<h2 id="explorer-heading" class="explorer-heading">Explorer</h2>
	</div>
	<nav class="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="Namespace explorer">
		<ul class="m-0 grid list-none gap-0 p-0">
			{#each data.catalogs as catalog (catalog.name)}
				{@const selected = catalog.name === data.selected.catalog}
				{@const isExpanded = selected && catalogExpanded}
				<li class="min-w-0">
					<div
						class={[
							'flex min-w-0 items-start gap-1 rounded py-0.5 pl-1 pr-2 text-xs',
							selected && !data.selected.namespace.length
								? 'bg-brand-soft font-semibold text-brand-strong'
								: 'text-app-fg hover:bg-app-sidebar-hover'
						]}
					>
						<button
							type="button"
							onclick={() =>
								selected
									? (catalogExpanded = !catalogExpanded)
									: goto(resolve(browseHref(catalog.name, [], '', organization?.slug)), {
											noScroll: true,
											keepFocus: true
										})}
							aria-label={`${isExpanded ? 'Collapse' : 'Expand'} catalog ${catalog.name}`}
							aria-expanded={isExpanded}
							class="grid size-6 shrink-0 place-items-center rounded text-app-muted hover:text-app-fg"
							>{#if isExpanded}<ChevronDown size={14} />{:else}<ChevronRight
									size={14}
								/>{/if}</button
						>
						<a
							href={resolve(browseHref(catalog.name, [], '', organization?.slug))}
							onclick={() => (catalogExpanded = true)}
							aria-current={selected && !data.selected.namespace.length ? 'page' : undefined}
							class="flex min-w-0 flex-1 items-start gap-1.5 py-1 text-inherit"
							><Database size={14} class="mt-0.5 shrink-0 text-brand-strong" /><span
								class="min-w-0 break-all">{catalog.name}</span
							></a
						>
					</div>
					{#if isExpanded}{@render branchContents([], 1)}{/if}
				</li>
			{/each}
		</ul>
		{#if !data.catalogs.length}<p class="px-3 py-2 text-xs text-app-muted">
				No accessible catalogs
			</p>{/if}
	</nav>
</section>

<style>
	.explorer-heading {
		margin: 0;
		padding: 0;
		border: 0;
		font-size: 0.75rem;
		font-weight: 600;
	}
	.folder-row {
		padding-left: calc(var(--tree-depth) * 0.7rem + 0.25rem);
	}
	.repository-row {
		padding-left: calc(var(--tree-depth) * 0.7rem + 1.8rem);
	}
</style>
