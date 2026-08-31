<script lang="ts">
	import {
		ArrowRight,
		CheckCircle2,
		Clock3,
		Database,
		Filter,
		Plus,
		Search,
		SlidersHorizontal
	} from '@lucide/svelte';
	import Badge from '$design/components/Badge.svelte';
	import LayerBadges from '$design/components/LayerBadges.svelte';
	import { selectedOrganization } from '$lib/stores/workspace';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let view = $state<'list' | 'compact'>('list');

	const kinds = [
		{ label: 'All assets', count: 24 },
		{ label: 'Datasets', count: 14 },
		{ label: 'Releases', count: 7 },
		{ label: 'Products', count: 3 }
	];
	const visibleHits = $derived($selectedOrganization === 'example-org' ? data.results.hits : []);
</script>

<svelte:head><title>Catalog · Huron</title></svelte:head>

<div class="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
	<div>
		<div
			class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.11em] text-app-muted"
		>
			<Database size={14} /> Lakehouse catalog
		</div>
		<h1>Search the catalog</h1>
		<p class="mt-2 max-w-2xl text-sm text-app-muted">
			Discover governed datasets across raw, bronze, silver, and gold layers.
		</p>
	</div>
	<a
		href="/ingestion"
		class="inline-flex h-9 items-center justify-center gap-2 self-start rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29] transition hover:bg-brand-strong sm:self-auto"
	>
		<Plus size={16} strokeWidth={2.4} /> Ingest data
	</a>
</div>

<form
	method="GET"
	action="/"
	role="search"
	class="mb-5 rounded-lg border border-app-line bg-app-card p-2 shadow-[var(--shadow-sm)]"
>
	<label class="relative block">
		<span class="visually-hidden">Search query</span>
		<Search
			size={19}
			class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
		/>
		<input
			id="q"
			name="q"
			type="search"
			value={data.q}
			placeholder="Search by dataset name, tag, owner, or description…"
			class="h-11 w-full rounded-md border-0 bg-transparent pl-10 pr-28 text-[15px] outline-none placeholder:text-app-muted"
		/>
		<button
			type="submit"
			class="absolute right-1 top-1/2 h-9 -translate-y-1/2 rounded-md bg-[#26333b] px-4 text-sm font-semibold text-white hover:bg-[#1b252b] dark:bg-brand dark:text-[#062d29]"
			>Search</button
		>
	</label>
</form>

<div class="mb-5 grid gap-3 sm:grid-cols-3">
	<div class="rounded-lg border border-app-line bg-app-card p-4">
		<div class="flex items-center justify-between">
			<span class="text-xs font-medium text-app-muted">Catalog assets</span><Database
				size={16}
				class="text-brand-strong"
			/>
		</div>
		<p class="mt-2 text-2xl font-semibold tracking-tight">
			{$selectedOrganization === 'example-org' ? '24' : '0'}
		</p>
		<p class="mt-1 text-xs text-app-muted">
			Across {$selectedOrganization === 'example-org' ? '2 active projects' : 'no active projects'}
		</p>
	</div>
	<div class="rounded-lg border border-app-line bg-app-card p-4">
		<div class="flex items-center justify-between">
			<span class="text-xs font-medium text-app-muted">Projection health</span><CheckCircle2
				size={16}
				class="text-app-success"
			/>
		</div>
		<p class="mt-2 text-2xl font-semibold tracking-tight">Healthy</p>
		<p class="mt-1 text-xs text-app-muted">
			Index {data.results.watermark.state === 'healthy'
				? `${data.results.watermark.lagSeconds}s behind`
				: 'unavailable'}
		</p>
	</div>
	<div class="rounded-lg border border-app-line bg-app-card p-4">
		<div class="flex items-center justify-between">
			<span class="text-xs font-medium text-app-muted">Last ingest</span><Clock3
				size={16}
				class="text-app-muted"
			/>
		</div>
		<p class="mt-2 text-2xl font-semibold tracking-tight">18 min</p>
		<p class="mt-1 text-xs text-app-muted">example-sweep · raw</p>
	</div>
</div>

<div class="grid gap-5 xl:grid-cols-[220px_minmax(0,1fr)]">
	<aside class="hidden xl:block">
		<div
			class="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.1em] text-app-muted"
		>
			<Filter size={14} /> Filters
		</div>
		<div class="overflow-hidden rounded-lg border border-app-line bg-app-card">
			<div class="border-b border-app-line p-3">
				<p class="mb-2 text-xs font-semibold text-app-fg">Asset type</p>
				<div class="grid gap-1">
					{#each kinds as kind, i}
						<button
							type="button"
							class="flex items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-app-sidebar-hover"
							class:bg-brand-soft={i === 0}
							class:text-brand-strong={i === 0}
							class:text-app-muted={i !== 0}
						>
							{kind.label}<span class="text-xs">{kind.count}</span>
						</button>
					{/each}
				</div>
			</div>
			{#each Object.entries(data.results.facets) as [name, values]}
				<div class="border-b border-app-line p-3 last:border-0">
					<p class="mb-2 text-xs font-semibold capitalize text-app-fg">{name}</p>
					<div class="grid gap-2">
						{#each values as value}
							<label class="flex items-center gap-2 text-xs text-app-muted">
								<input type="checkbox" class="size-3.5 accent-[var(--brand-strong)]" />
								<span class="flex-1 capitalize">{value.value}</span><span>{value.count}</span>
							</label>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	</aside>

	<section aria-label="Catalog results">
		<div class="mb-3 flex items-center justify-between gap-3">
			<div>
				<h2 class="m-0 border-0 p-0 text-base font-semibold">
					{data.q ? `Results for “${data.q}”` : 'Recently active'}
				</h2>
				<p class="mt-0.5 text-xs text-app-muted">
					{visibleHits.length} assets · visibility filtered
				</p>
			</div>
			<div class="flex items-center gap-2">
				<button
					type="button"
					class="inline-flex h-8 items-center gap-1.5 rounded-md border border-app-line bg-app-card px-2.5 text-xs text-app-muted xl:hidden"
					><SlidersHorizontal size={14} /> Filters</button
				>
				<div class="flex rounded-md border border-app-line bg-app-card p-0.5">
					<button
						type="button"
						onclick={() => (view = 'list')}
						class="rounded px-2 py-1 text-xs"
						class:bg-app-sidebar-hover={view === 'list'}
						class:text-app-fg={view === 'list'}
						class:text-app-muted={view !== 'list'}>Comfortable</button
					>
					<button
						type="button"
						onclick={() => (view = 'compact')}
						class="rounded px-2 py-1 text-xs"
						class:bg-app-sidebar-hover={view === 'compact'}
						class:text-app-fg={view === 'compact'}
						class:text-app-muted={view !== 'compact'}>Compact</button
					>
				</div>
			</div>
		</div>

		<div class="overflow-hidden rounded-lg border border-app-line bg-app-card">
			{#each visibleHits as hit, i}
				<a
					href={hit.slugPath}
					class="group block border-b border-app-line px-4 last:border-0 hover:bg-app-sidebar-hover"
					class:py-4={view === 'list'}
					class:py-2.5={view === 'compact'}
				>
					<div class="flex items-start gap-3">
						<div
							class="mt-0.5 grid size-9 shrink-0 place-items-center rounded-md border border-app-line bg-app-bg text-brand-strong"
						>
							<Database size={17} />
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-center gap-2">
								<h3 class="m-0 text-sm font-semibold text-app-fg group-hover:text-brand-strong">
									{hit.title}
								</h3>
								<Badge>{hit.kind}</Badge>
								{#if hit.stale}<Badge tone="warn" title={hit.stale.reason}>stale</Badge>{/if}
							</div>
							{#if view === 'list'}<p class="mt-1 max-w-3xl text-sm text-app-muted">
									{hit.snippet}
								</p>{/if}
							<div class="mt-2 flex flex-wrap items-center gap-3">
								<LayerBadges layers={hit.layers} /><span class="text-[11px] text-app-muted"
									>Updated {i === 0 ? '18 min' : '2 hr'} ago · {hit.classification}</span
								>
							</div>
						</div>
						<ArrowRight
							size={16}
							class="mt-2 shrink-0 text-app-muted transition group-hover:translate-x-0.5 group-hover:text-brand-strong"
						/>
					</div>
				</a>
			{/each}
			{#if visibleHits.length === 0}<div class="px-5 py-14 text-center">
					<Database size={24} class="mx-auto text-app-muted" />
					<p class="mt-3 text-sm font-semibold">No visible assets</p>
					<p class="mt-1 text-xs text-app-muted">
						Switch organizations or create a project to begin.
					</p>
				</div>{/if}
		</div>
	</section>
</div>
