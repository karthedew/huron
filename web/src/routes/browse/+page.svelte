<script lang="ts">
	import { CheckCircle2, ChevronRight, CircleAlert, Database, Folder } from '@lucide/svelte';
	import { navigating, page } from '$app/state';
	import { resolve } from '$app/paths';
	import '$design/polaris.css';
	import EmptyState from '$design/components/EmptyState.svelte';
	import NamespaceExplorer from '$design/components/polaris/NamespaceExplorer.svelte';
	import NamespaceContents from '$design/components/polaris/NamespaceContents.svelte';
	import DatasetDetail from '$design/components/polaris/DatasetDetail.svelte';
	import GenericTableDetail from '$design/components/polaris/GenericTableDetail.svelte';
	import { browseHref } from '$lib/stores/workspace';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	const scientificTable = $derived(data.loadedIcebergTable ?? data.loadedTable);
	const table = $derived(data.loadedGenericTable ?? scientificTable);
	const message = $derived(form?.message ?? data.notice);
	const success = $derived(form?.message ? form.success : true);
	const folderName = $derived(
		data.selected.namespace.at(-1) ??
			(data.selected.catalog || data.organization?.name || 'Organizations')
	);
	const organizationHref = $derived(
		data.organization
			? (`/browse?organization=${encodeURIComponent(data.organization.slug)}` as const)
			: '/browse'
	);
	function href(changes: Record<string, string | null>): '/browse' | `/browse?${string}` {
		const query = new URLSearchParams(page.url.searchParams);
		if (data.selectedOrganization) query.set('organization', data.selectedOrganization);
		if (!query.has('catalog') && data.selected.catalog) query.set('catalog', data.selected.catalog);
		for (const key of [...query.keys()]) if (key.startsWith('/')) query.delete(key);
		for (const [key, value] of Object.entries(changes)) {
			if (value === null) query.delete(key);
			else query.set(key, value);
		}
		return query.size ? `/browse?${query}` : '/browse';
	}
</script>

<svelte:head><title>{table?.name ?? folderName ?? 'Browse'} · Huron</title></svelte:head>

<div
	class="polaris-workspace flex min-h-0 w-full min-w-0 flex-col bg-app-card md:h-[calc(100dvh-64px)] md:flex-row"
	aria-busy={!!navigating.to}
>
	<div class="flex max-h-64 min-w-0 shrink-0 flex-col md:max-h-none md:w-[230px] lg:w-[260px]">
		{#key `${data.selectedOrganization}:${data.selected.catalog}`}
			<NamespaceExplorer {data} organization={data.organization} />
		{/key}
	</div>
	<div class="flex min-h-0 min-w-0 flex-1 flex-col">
		<nav
			class="flex min-h-10 shrink-0 flex-wrap items-center gap-1.5 border-b border-app-line px-4 py-2 text-xs text-app-muted"
			aria-label="Namespace path"
		>
			<a
				href={resolve(organizationHref)}
				class="break-all text-app-muted"
				aria-current={!data.selected.catalog ? 'page' : undefined}
				>{data.organization?.name ?? 'Organizations'}</a
			>
			{#if data.selected.catalog}
				<ChevronRight size={11} class="shrink-0" />
				<a
					href={resolve(browseHref(data.selected.catalog, [], '', data.selectedOrganization))}
					class="break-all text-app-muted">{data.selected.catalog}</a
				>
			{/if}
			{#each data.selected.namespace as level, index (JSON.stringify(data.selected.namespace.slice(0, index + 1)))}<ChevronRight
					size={11}
					class="shrink-0"
				/><a
					href={resolve(
						browseHref(
							data.selected.catalog,
							data.selected.namespace.slice(0, index + 1),
							'',
							data.selectedOrganization
						)
					)}
					class="break-all text-app-muted">{level}</a
				>{/each}
			{#if table}<ChevronRight size={11} class="shrink-0" /><span class="break-all text-app-fg"
					>{table.name}</span
				>{/if}
			{#if navigating.to}<span role="status" class="ml-auto text-[10px]">Loading…</span>{/if}
		</nav>
		<div class="min-h-0 min-w-0 flex-1 overflow-y-auto">
			{#if message}<div
					role={success ? 'status' : 'alert'}
					class={[
						'm-4 flex items-start gap-2 rounded border px-3 py-2 text-xs',
						success
							? 'border-app-success/35 bg-brand-soft'
							: 'border-app-danger/35 bg-app-danger/10'
					]}
				>
					{#if success}<CheckCircle2
							size={15}
							class="mt-0.5 shrink-0 text-app-success"
						/>{:else}<CircleAlert size={15} class="mt-0.5 shrink-0 text-app-danger" />{/if}
					<p>{message}</p>
				</div>{/if}
			{#if form?.credentialSummary}<div
					role="status"
					class="m-4 rounded border border-app-line p-3 text-xs"
				>
					<p class="font-semibold">Storage access · {form.credentialSummary.accessMode}</p>
					<p class="mt-1 text-app-muted">{form.credentialSummary.message}</p>
					{#each form.credentialSummary.configurations as configuration (configuration.prefix)}<p
							class="mt-2 break-all text-app-muted"
						>
							{configuration.prefix} · {configuration.hasCredentials
								? 'Credentials available'
								: 'No credentials'}{configuration.expiresAt
								? ` · expires ${configuration.expiresAt}`
								: ''}
						</p>{/each}
				</div>{/if}
			{#if data.catalogError}<p
					role="alert"
					class="m-4 rounded border border-app-danger/35 p-3 text-xs"
				>
					{data.catalogError}
				</p>{/if}
			{#if !data.catalogs.length}
				<div class="p-6">
					<EmptyState
						title="No catalogs available"
						detail="An administrator can assign your account to catalogs in this organization. Your account has no implicit catalog access."
					/>
				</div>
			{:else if !data.selected.catalog}
				<header class="flex min-w-0 items-start gap-2.5 border-b border-app-line px-4 py-3">
					<Folder size={19} class="mt-0.5 shrink-0 text-app-muted" />
					<div class="min-w-0">
						<h1 class="break-all text-xl font-semibold tracking-normal">{folderName}</h1>
						<p class="mt-1 text-xs text-app-muted">
							{data.catalogs.length}
							{data.catalogs.length === 1 ? 'catalog' : 'catalogs'}
						</p>
					</div>
				</header>
				<ul aria-label="Organization catalogs" class="m-0 list-none p-0">
					{#each data.catalogs as catalog (catalog.name)}
						<li class="border-b border-app-line">
							<a
								href={resolve(browseHref(catalog.name, [], '', data.selectedOrganization))}
								aria-label={catalog.name}
								class="flex min-w-0 items-start gap-3 px-4 py-3 text-sm text-app-fg hover:bg-app-sidebar-hover"
							>
								<Database size={17} class="mt-0.5 shrink-0 text-brand-strong" />
								<span class="min-w-0 flex-1">
									<span class="block break-all font-medium">{catalog.name}</span>
									{#if catalog.properties.description}<span
											class="mt-1 block break-words text-xs text-app-muted"
											>{catalog.properties.description}</span
										>{/if}
								</span>
								<span class="mt-0.5 shrink-0 text-xs text-app-muted"
									>{catalog.storageConfigInfo.storageType}</span
								>
								<ChevronRight size={14} class="mt-0.5 shrink-0 text-app-muted" />
							</a>
						</li>
					{/each}
				</ul>
			{:else if data.loadedGenericTable}
				<GenericTableDetail {data} table={data.loadedGenericTable} {href} />
			{:else if scientificTable}
				<DatasetDetail {data} table={scientificTable} inspection={data.inspection} {href} />
			{:else}
				<header class="flex min-w-0 items-start gap-2.5 border-b border-app-line px-4 py-3">
					{#if data.selected.namespace.length}<Folder
							size={19}
							class="mt-0.5 shrink-0 text-app-muted"
						/>{:else}<Database size={19} class="mt-0.5 shrink-0 text-app-muted" />{/if}
					<h1 class="min-w-0 break-all text-xl font-semibold tracking-normal">{folderName}</h1>
				</header>
				<NamespaceContents {data} {href} organization={data.selectedOrganization} />
			{/if}
		</div>
	</div>
</div>
