<script lang="ts">
	import {
		Building2,
		ChevronDown,
		ChevronLeft,
		ChevronRight,
		Database,
		Folder,
		FolderOpen,
		Search,
		Table2,
		X
	} from '@lucide/svelte';
	import LayerBadges from '$design/components/LayerBadges.svelte';
	import LifecycleChip from '$design/components/LifecycleChip.svelte';
	import { selectedOrganization } from '$lib/stores/workspace';
	import type { Layer } from '$api/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let selectedProjectSlug = $state('');
	let query = $state('');
	let lifecycleFilter = $state('all');
	let classificationFilter = $state('all');
	let profileFilter = $state('all');
	let layerFilter = $state<'all' | Layer>('all');
	let tagFilter = $state('all');
	let currentPage = $state(1);
	let pageSize = $state(25);
	let previousScope = $state('');

	const selectClass =
		'h-8 min-w-28 rounded-md border border-app-line bg-app-card px-2 text-xs text-app-fg outline-none focus:border-brand-strong';
	const unique = (values: string[]) => [...new Set(values)].sort((a, b) => a.localeCompare(b));
	const currentOrg = $derived(
		data.organizations.find((organization) => organization.slug === $selectedOrganization) ??
			data.organizations[0]
	);
	const orgProjects = $derived(
		data.projects.filter((project) => project.orgSlug === currentOrg?.slug)
	);
	const selectedProject = $derived(
		orgProjects.find((project) => project.slug === selectedProjectSlug) ?? orgProjects[0]
	);
	const scopedDatasets = $derived(
		data.datasets.filter(
			(dataset) =>
				dataset.orgSlug === currentOrg?.slug && dataset.projectSlug === selectedProject?.slug
		)
	);
	const lifecycleOptions = $derived(unique(scopedDatasets.map((dataset) => dataset.lifecycle)));
	const classificationOptions = $derived(
		unique(scopedDatasets.map((dataset) => dataset.classification))
	);
	const profileOptions = $derived(unique(scopedDatasets.map((dataset) => dataset.profile)));
	const tagOptions = $derived(unique(scopedDatasets.flatMap((dataset) => dataset.tags)));
	const visibleDatasets = $derived(
		scopedDatasets.filter((dataset) => {
			const materializedLayers = (Object.keys(dataset.layers) as Layer[]).filter(
				(layer) => dataset.layers[layer].state !== 'absent'
			);
			const searchable = [
				dataset.name,
				dataset.description,
				dataset.lifecycle,
				dataset.classification,
				dataset.profile,
				...dataset.tags,
				...materializedLayers
			]
				.join(' ')
				.toLowerCase();

			return (
				searchable.includes(query.trim().toLowerCase()) &&
				(lifecycleFilter === 'all' || dataset.lifecycle === lifecycleFilter) &&
				(classificationFilter === 'all' || dataset.classification === classificationFilter) &&
				(profileFilter === 'all' || dataset.profile === profileFilter) &&
				(tagFilter === 'all' || dataset.tags.includes(tagFilter)) &&
				(layerFilter === 'all' || dataset.layers[layerFilter].state !== 'absent')
			);
		})
	);
	const activeFilterCount = $derived(
		[lifecycleFilter, classificationFilter, profileFilter, layerFilter, tagFilter].filter(
			(value) => value !== 'all'
		).length
	);
	const totalPages = $derived(Math.max(1, Math.ceil(visibleDatasets.length / pageSize)));
	const safePage = $derived(Math.min(currentPage, totalPages));
	const pageStart = $derived(visibleDatasets.length === 0 ? 0 : (safePage - 1) * pageSize + 1);
	const pageEnd = $derived(Math.min(safePage * pageSize, visibleDatasets.length));
	const pageDatasets = $derived(
		visibleDatasets.slice((safePage - 1) * pageSize, safePage * pageSize)
	);

	$effect(() => {
		const scope = `${currentOrg?.slug ?? ''}/${selectedProject?.slug ?? ''}`;
		if (scope !== previousScope) {
			previousScope = scope;
			currentPage = 1;
		}
	});

	function chooseProject(slug: string) {
		selectedProjectSlug = slug;
		currentPage = 1;
	}

	function resetPage() {
		currentPage = 1;
	}

	function clearFilters() {
		query = '';
		lifecycleFilter = 'all';
		classificationFilter = 'all';
		profileFilter = 'all';
		layerFilter = 'all';
		tagFilter = 'all';
		currentPage = 1;
	}
</script>

<svelte:head><title>Browse · Huron</title></svelte:head>

<div class="mb-5">
	<div
		class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.11em] text-app-muted"
	>
		<Table2 size={14} /> Catalog explorer
	</div>
	<h1>Browse the lakehouse</h1>
	<p class="mt-2 text-sm text-app-muted">
		Explore projects and datasets within {currentOrg?.name ?? 'your active organization'}.
	</p>
</div>

<div
	data-testid="catalog-explorer"
	class="grid min-h-[560px] overflow-hidden rounded-lg border border-app-line bg-app-card shadow-[var(--shadow-sm)] lg:h-[calc(100dvh-13rem)] lg:min-h-[480px] lg:max-h-[760px] lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[260px_minmax(0,1fr)]"
>
	<section
		class="border-b border-app-line bg-app-bg/35 lg:min-h-0 lg:overflow-y-auto lg:border-b-0 lg:border-r"
	>
		<div class="flex h-11 items-center justify-between border-b border-app-line bg-app-bg px-3">
			<h2 class="m-0 border-0 p-0 text-xs font-semibold uppercase tracking-[0.08em] text-app-muted">
				Project explorer
			</h2>
			<span class="text-[11px] tabular-nums text-app-muted">{orgProjects.length}</span>
		</div>

		<div class="p-2" aria-label={`${currentOrg?.name ?? 'Organization'} project tree`}>
			<div
				class="flex h-8 items-center gap-1.5 rounded-md px-1.5 text-xs font-semibold text-app-fg"
			>
				<ChevronDown size={14} class="shrink-0 text-app-muted" />
				<Building2 size={15} class="shrink-0 text-brand-strong" />
				<span class="truncate">{currentOrg?.name ?? 'Organization'}</span>
			</div>

			<div class="relative ml-[13px] border-l border-app-line pl-3">
				{#each orgProjects as project}
					<div class="group relative flex items-center">
						<span class="absolute -left-3 top-1/2 w-3 border-t border-app-line"></span>
						<button
							type="button"
							onclick={() => chooseProject(project.slug)}
							class="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-md px-2 text-left text-xs transition"
							class:bg-brand-soft={selectedProject?.slug === project.slug}
							class:text-brand-strong={selectedProject?.slug === project.slug}
							class:text-app-muted={selectedProject?.slug !== project.slug}
							class:hover:bg-app-sidebar-hover={selectedProject?.slug !== project.slug}
							aria-pressed={selectedProject?.slug === project.slug}
							aria-label={`${project.name}, ${project.datasetCount} datasets`}
						>
							{#if selectedProject?.slug === project.slug}<FolderOpen
									size={15}
									class="shrink-0"
								/>{:else}<Folder size={15} class="shrink-0" />{/if}
							<span class="truncate font-medium">{project.name}</span>
							<span class="ml-auto text-[10px] tabular-nums text-app-muted"
								>{project.datasetCount}</span
							>
						</button>
						<a
							href={`/${project.orgSlug}/${project.slug}`}
							class="grid size-7 shrink-0 place-items-center rounded-md text-app-muted opacity-0 hover:bg-app-card hover:text-brand-strong focus:opacity-100 group-hover:opacity-100"
							aria-label={`Open ${project.name}`}><ChevronRight size={13} /></a
						>
					</div>
				{/each}
			</div>

			{#if orgProjects.length === 0}
				<p class="px-3 py-8 text-center text-xs text-app-muted">
					No visible projects in this organization.
				</p>
			{/if}
		</div>
	</section>

	<section class="min-w-0 lg:flex lg:min-h-0 lg:flex-col">
		<div
			class="flex min-h-11 flex-col gap-2 border-b border-app-line bg-app-bg px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
		>
			<div class="min-w-0">
				<h2 class="m-0 truncate border-0 p-0 text-sm font-semibold text-app-fg">
					Datasets in {selectedProject?.name ?? 'selected project'}
				</h2>
				<p class="mt-0.5 truncate text-[10px] text-app-muted">
					{currentOrg?.name ?? 'Organization'} / {selectedProject?.name ?? 'No project selected'} ·
					{visibleDatasets.length} matching
				</p>
			</div>
			<label class="relative block sm:w-64"
				><span class="visually-hidden">Filter datasets</span><Search
					size={14}
					class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-app-muted"
				/><input
					bind:value={query}
					oninput={resetPage}
					type="search"
					placeholder="Name or metadata"
					class="h-8 w-full rounded-md border border-app-line bg-app-card pl-8 pr-3 text-xs outline-none focus:border-brand-strong"
				/></label
			>
		</div>

		<div
			class="flex items-center gap-2 overflow-x-auto border-b border-app-line bg-app-bg/55 px-3 py-2"
		>
			<select
				bind:value={lifecycleFilter}
				onchange={resetPage}
				aria-label="Filter by lifecycle"
				class={selectClass}
			>
				<option value="all">All states</option>
				{#each lifecycleOptions as lifecycle}<option value={lifecycle}>{lifecycle}</option>{/each}
			</select>
			<select
				bind:value={classificationFilter}
				onchange={resetPage}
				aria-label="Filter by classification"
				class={selectClass}
			>
				<option value="all">All classifications</option>
				{#each classificationOptions as classification}<option value={classification}
						>{classification}</option
					>{/each}
			</select>
			<select
				bind:value={profileFilter}
				onchange={resetPage}
				aria-label="Filter by profile"
				class={selectClass}
			>
				<option value="all">All profiles</option>
				{#each profileOptions as profile}<option value={profile}>{profile}</option>{/each}
			</select>
			<select
				bind:value={layerFilter}
				onchange={resetPage}
				aria-label="Filter by materialized layer"
				class={selectClass}
			>
				<option value="all">All layers</option>
				<option value="raw">Raw available</option>
				<option value="bronze">Bronze available</option>
				<option value="silver">Silver available</option>
				<option value="gold">Gold available</option>
			</select>
			<select
				bind:value={tagFilter}
				onchange={resetPage}
				aria-label="Filter by tag"
				class={selectClass}
			>
				<option value="all">All tags</option>
				{#each tagOptions as tag}<option value={tag}>{tag}</option>{/each}
			</select>
			{#if activeFilterCount > 0 || query}
				<button
					type="button"
					onclick={clearFilters}
					class="ml-auto inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
					><X size={13} /> Clear {activeFilterCount > 0 ? `(${activeFilterCount})` : ''}</button
				>
			{/if}
		</div>

		<div
			data-testid="dataset-results"
			class="divide-y divide-app-line lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
		>
			{#each pageDatasets as dataset}
				<a
					href={`/${dataset.orgSlug}/${dataset.projectSlug}/${dataset.slug}`}
					class="group block p-3 hover:bg-app-sidebar-hover"
				>
					<div class="flex items-start gap-3">
						<span
							class="grid size-8 shrink-0 place-items-center rounded-md border border-app-line bg-app-bg text-brand-strong"
							><Database size={15} /></span
						>
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-center gap-2">
								<h3 class="m-0 text-sm font-semibold group-hover:text-brand-strong">
									{dataset.name}
								</h3>
								<LifecycleChip state={dataset.lifecycle} />
							</div>
							<p class="mt-0.5 line-clamp-1 text-xs text-app-muted">{dataset.description}</p>
							<p class="mt-1 text-[10px] text-app-muted">
								{dataset.classification} · {dataset.profile} · {dataset.releaseCount} releases · {dataset.tags.join(
									', '
								)}
							</p>
							<div class="mt-2"><LayerBadges layers={dataset.layers} /></div>
						</div>
						<ChevronRight
							size={16}
							class="mt-1.5 shrink-0 text-app-muted group-hover:text-brand-strong"
						/>
					</div>
				</a>
			{/each}
			{#if visibleDatasets.length === 0}
				<div class="px-4 py-12 text-center">
					<Database size={22} class="mx-auto mb-2 text-app-muted" />
					<p class="text-sm font-medium text-app-fg">No datasets found</p>
					<p class="mt-1 text-xs text-app-muted">
						Try another project or clear the metadata filters.
					</p>
				</div>
			{/if}
		</div>

		<div
			class="flex min-h-11 shrink-0 flex-wrap items-center gap-3 border-t border-app-line bg-app-bg px-3 py-1.5 text-[11px] text-app-muted"
			aria-label="Dataset pagination"
		>
			<span class="tabular-nums">Showing {pageStart}–{pageEnd} of {visibleDatasets.length}</span>
			<label class="ml-auto flex items-center gap-1.5">
				<span>Rows</span>
				<select
					bind:value={pageSize}
					onchange={resetPage}
					aria-label="Datasets per page"
					class="h-7 rounded-md border border-app-line bg-app-card px-1.5 text-[11px] text-app-fg"
				>
					<option value={25}>25</option>
					<option value={50}>50</option>
					<option value={100}>100</option>
				</select>
			</label>
			<span class="tabular-nums">Page {safePage} of {totalPages}</span>
			<div class="flex items-center gap-1">
				<button
					type="button"
					onclick={() => (currentPage = Math.max(1, safePage - 1))}
					disabled={safePage === 1}
					class="grid size-7 place-items-center rounded-md border border-app-line bg-app-card text-app-muted enabled:hover:text-app-fg disabled:cursor-not-allowed disabled:opacity-40"
					aria-label="Previous dataset page"><ChevronLeft size={14} /></button
				>
				<button
					type="button"
					onclick={() => (currentPage = Math.min(totalPages, safePage + 1))}
					disabled={safePage === totalPages}
					class="grid size-7 place-items-center rounded-md border border-app-line bg-app-card text-app-muted enabled:hover:text-app-fg disabled:cursor-not-allowed disabled:opacity-40"
					aria-label="Next dataset page"><ChevronRight size={14} /></button
				>
			</div>
		</div>
	</section>
</div>
