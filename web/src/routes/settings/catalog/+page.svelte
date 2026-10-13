<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { Building2 } from '@lucide/svelte';
	import AccessPanel from '$design/components/polaris/AccessPanel.svelte';
	import CatalogSettingsPanel from '$design/components/polaris/CatalogSettingsPanel.svelte';
	import CatalogMembersPanel from '$design/components/polaris/CatalogMembersPanel.svelte';
	import '$design/polaris.css';
	import type { PageData, ActionData } from './$types';
	let { data, form }: { data: PageData; form: ActionData } = $props();
	const active = $derived(
		['general', 'users', 'access'].includes(data.activeTab) ? data.activeTab : 'users'
	);
	function href(
		changes: Record<string, string | null>
	): '/settings/catalog' | `/settings/catalog?${string}` {
		const query = new URLSearchParams(page.url.searchParams);
		for (const key of [...query.keys()]) if (key.startsWith('/')) query.delete(key);
		for (const [key, value] of Object.entries(changes))
			value === null ? query.delete(key) : query.set(key, value);
		return query.size ? `/settings/catalog?${query}` : '/settings/catalog';
	}
</script>

<svelte:head><title>Catalog settings · Huron</title></svelte:head>

<div class="polaris-workspace min-w-0">
	<div class="mb-6 flex flex-wrap items-start justify-between gap-4">
		<div>
			<p class="mb-2 flex items-center gap-2 text-xs font-semibold text-app-muted">
				<Building2 size={15} /> Polaris catalog
			</p>
			<h1>Catalog settings</h1>
			<p class="mt-2 break-all text-sm text-app-muted">
				{data.catalog?.name ?? 'Select a catalog'}
			</p>
		</div>
		<form method="GET" action={resolve('/settings/catalog')} class="flex flex-wrap items-end gap-2">
			<input type="hidden" name="tab" value={active} /><label
				>Catalog<select name="catalog" value={data.selected.catalog}
					>{#each data.catalogs as catalog (catalog.name)}<option value={catalog.name}
							>{catalog.name}</option
						>{/each}</select
				></label
			><button class="secondary" type="submit">Select catalog</button>
		</form>
	</div>
	<nav
		class="mb-5 flex flex-wrap gap-2 border-b border-app-line"
		aria-label="Catalog settings sections"
	>
		{#each [{ id: 'general', label: 'General & storage' }, { id: 'users', label: 'Users' }, { id: 'access', label: 'Advanced grants' }] as tab (tab.id)}<a
				class={['section-tab', active === tab.id && 'active']}
				href={resolve(href({ tab: tab.id }))}
				aria-current={active === tab.id ? 'page' : undefined}>{tab.label}</a
			>{/each}
	</nav>
	{#if form}<p
			class={[
				'mb-5 rounded-md border p-3 text-sm',
				form.success
					? 'border-app-success/40 bg-brand-soft'
					: 'border-app-danger/40 bg-app-danger/10'
			]}
			role={form.success ? 'status' : 'alert'}
		>
			{form.message}
		</p>{/if}
	{#if data.notice}<p class="notice mb-5" role="status">{data.notice}</p>{/if}
	{#if data.catalog}
		{#if active === 'general'}<CatalogSettingsPanel
				catalog={data.catalog}
				allowDrop={data.isAdmin}
			/>
		{:else if active === 'users'}
			{#if data.membershipError}<p class="notice" role="status">
					{data.membershipError}
				</p>{:else}<CatalogMembersPanel catalog={data.catalog.name} members={data.members} />{/if}
		{:else}<AccessPanel
				{data}
				{href}
				realmAdmin={false}
				managedCatalogRoles={['huron_reader', 'huron_writer', 'huron_catalog_admin']}
			/>{/if}
	{:else}<section class="panel">
			<h2>No catalogs available</h2>
			<p class="hint mt-2">
				A Huron administrator can create a Polaris catalog and grant your user access.
			</p>
			{#if data.isAdmin}<a class="mt-4 inline-block" href={resolve('/admin')}>Open Administration</a
				>{/if}
		</section>{/if}
	<div class="mt-5 flex flex-wrap gap-4 text-sm">
		{#if data.catalog}<a
				href={resolve(`/browse?catalog=${encodeURIComponent(data.selected.catalog)}`)}
				>Browse this catalog</a
			>{/if}{#if data.isAdmin}<a href={resolve('/admin?tab=users')}>Create or manage Huron logins</a
			>{/if}
	</div>
</div>
