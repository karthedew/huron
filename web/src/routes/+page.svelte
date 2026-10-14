<script lang="ts">
	import { ArrowRight, Database, Plus, Search, Settings } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import EmptyState from '$design/components/EmptyState.svelte';
	import { browseHref } from '$lib/stores/workspace';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>Catalog · Huron</title></svelte:head>

<div class="mb-6 flex flex-wrap items-start justify-between gap-4">
	<div class="min-w-0">
		<p class="mb-2 flex items-center gap-2 text-xs font-semibold text-brand-strong">
			<Database size={14} />
			{data.organization?.name ?? 'Organizations'}
		</p>
		<h1>{data.organization?.name ?? 'Your organizations'}</h1>
		<p class="mt-2 max-w-2xl text-sm text-app-muted">
			Browse domain catalogs and their Raw collections, Iceberg tables, and Icechunk arrays.
		</p>
	</div>
	{#if data.user?.isAdmin}
		<a
			href={resolve(
				`/admin?tab=catalogs&organization=${encodeURIComponent(data.selectedOrganization)}`
			)}
			class="inline-flex h-9 items-center gap-2 rounded-md border border-brand-strong bg-brand-soft px-3 text-sm font-semibold text-brand-strong"
		>
			<Plus size={16} /> Create catalog
		</a>
	{/if}
</div>

<form
	method="GET"
	action={resolve('/')}
	role="search"
	class="mb-6 flex gap-2 rounded-lg border border-app-line bg-app-card p-2"
>
	{#if data.selectedOrganization}<input
			type="hidden"
			name="organization"
			value={data.selectedOrganization}
		/>{/if}<label class="relative min-w-0 flex-1">
		<span class="visually-hidden">Search query</span>
		<Search
			size={17}
			class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
		/>
		<input
			name="q"
			type="search"
			value={data.q}
			placeholder="Search visible catalog names and properties…"
			class="h-10 w-full rounded-md bg-transparent pl-10 pr-3 text-sm outline-none placeholder:text-app-muted"
		/>
	</label>
	<button
		type="submit"
		class="rounded-md border border-brand-strong bg-brand-soft px-4 text-sm font-semibold text-brand-strong"
		>Search</button
	>
</form>

{#if data.catalogError}
	<div
		role="alert"
		class="mb-5 rounded-lg border border-app-danger/35 bg-app-danger/10 px-4 py-3 text-sm"
	>
		{data.catalogError}
	</div>
{/if}

<div class="mb-4 flex flex-wrap items-center justify-between gap-2">
	<h2 class="m-0 border-0 p-0 text-base font-semibold">Catalogs</h2>
	<p class="text-xs text-app-muted">
		{data.catalogs.length} visible {data.catalogs.length === 1 ? 'catalog' : 'catalogs'}
	</p>
</div>

{#if data.catalogs.length}
	<div class="grid gap-4 lg:grid-cols-2">
		{#each data.catalogs as catalog (catalog.name)}
			<article
				class="min-w-0 rounded-lg border border-app-line bg-app-card p-5 shadow-[var(--shadow-sm)]"
			>
				<div class="flex items-start gap-3">
					<span
						class="grid size-10 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-strong"
						><Database size={20} /></span
					>
					<div class="min-w-0 flex-1">
						<h3 class="m-0 break-all text-base font-semibold">
							<a
								href={resolve(browseHref(catalog.name, [], '', data.selectedOrganization))}
								class="text-app-fg hover:text-brand-strong">{catalog.name}</a
							>
						</h3>
						<p class="mt-1 text-xs text-app-muted">
							Polaris catalog · {catalog.storageConfigInfo.storageType} storage
						</p>
					</div>
				</div>
				{#if catalog.properties.description}<p class="mt-4 break-words text-sm text-app-muted">
						{catalog.properties.description}
					</p>{/if}
				{#if catalog.properties['default-base-location']}<p
						class="mt-4 break-all font-mono text-xs text-app-muted"
					>
						{catalog.properties['default-base-location']}
					</p>{/if}
				<div class="mt-5 flex flex-wrap items-center gap-4 border-t border-app-line pt-4">
					<a
						href={resolve(browseHref(catalog.name, [], '', data.selectedOrganization))}
						class="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-strong"
						>Browse datasets <ArrowRight size={15} /></a
					>
					<a
						href={resolve(
							`/settings/catalog?catalog=${encodeURIComponent(catalog.name)}&organization=${encodeURIComponent(data.selectedOrganization)}`
						)}
						class="ml-auto inline-flex items-center gap-1.5 text-xs text-app-muted hover:text-app-fg"
						><Settings size={14} /> Catalog settings</a
					>
				</div>
			</article>
		{/each}
	</div>
{:else}
	<EmptyState
		title={data.q ? 'No matching catalogs' : 'No catalogs available'}
		detail={data.q
			? 'Try another name, storage type, or catalog property.'
			: 'An administrator can add you to an organization and assign catalog access in Polaris.'}
	/>
{/if}
