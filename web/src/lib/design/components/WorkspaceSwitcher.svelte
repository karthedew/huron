<script lang="ts">
	import { Building2, Check, ChevronsUpDown, Database, Plus } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { browseHref } from '$lib/stores/workspace';
	import type { HuronOrganizationSummary, PolarisCatalog } from '$api/types';

	let {
		organizations,
		catalogs,
		selectedOrganization,
		selectedCatalog,
		isAdmin = false
	}: {
		organizations: HuronOrganizationSummary[];
		catalogs: PolarisCatalog[];
		selectedOrganization: string;
		selectedCatalog: string;
		isAdmin?: boolean;
	} = $props();
	let organizationMenu = $state<HTMLDetailsElement>();
	let catalogMenu = $state<HTMLDetailsElement>();
	const current = $derived(organizations.find((entry) => entry.slug === selectedOrganization));
	function closeMenus() {
		if (organizationMenu) organizationMenu.open = false;
		if (catalogMenu) catalogMenu.open = false;
	}
	function closeFromOutside(event: MouseEvent) {
		for (const menu of [organizationMenu, catalogMenu])
			if (menu?.open && event.target instanceof Node && !menu.contains(event.target))
				menu.open = false;
	}
	function closeFromKeyboard(event: KeyboardEvent) {
		if (event.key !== 'Escape') return;
		for (const menu of [organizationMenu, catalogMenu]) {
			if (!menu?.open) continue;
			menu.open = false;
			menu.querySelector('summary')?.focus();
		}
	}
</script>

<svelte:window onclick={closeFromOutside} onkeydown={closeFromKeyboard} />

<div class="relative flex min-w-0 items-center gap-1.5">
	<details class="min-w-0" bind:this={organizationMenu}>
		<summary
			class="flex h-9 cursor-pointer list-none items-center gap-2 rounded-md border border-app-line bg-app-card px-2 text-sm hover:border-app-line-strong [&::-webkit-details-marker]:hidden"
			aria-label="Switch organization"
			title={current?.name ?? 'Select organization'}
		>
			<Building2 size={16} class="shrink-0 text-brand-strong" />
			<span class="hidden max-w-36 truncate lg:block">{current?.name ?? 'Organization'}</span>
			<ChevronsUpDown size={13} class="shrink-0 text-app-muted" />
		</summary>
		<div
			class="absolute right-0 top-11 z-50 max-h-[70dvh] w-[min(288px,80vw)] overflow-y-auto rounded-lg border border-app-line bg-app-raised p-1.5 shadow-[var(--shadow-popover)]"
		>
			<p class="px-2.5 py-2 text-xs font-semibold text-app-muted">Organizations</p>
			{#each organizations as organization (organization.id)}
				<a
					href={resolve(`/?organization=${encodeURIComponent(organization.slug)}`)}
					onclick={closeMenus}
					aria-current={organization.slug === selectedOrganization ? 'true' : undefined}
					class="flex min-w-0 items-center gap-2 rounded-md px-2.5 py-2 hover:bg-app-sidebar-hover"
				>
					<span class="min-w-0 flex-1"
						><span class="block break-words text-sm font-medium">{organization.name}</span><span
							class="block text-xs text-app-muted"
							>{organization.catalogNames.length} accessible catalogs · {organization.role ===
							'admin'
								? 'Administrator'
								: 'Member'}</span
						></span
					>
					{#if organization.slug === selectedOrganization}<Check
							size={16}
							class="shrink-0 text-brand-strong"
						/>{/if}
				</a>
			{:else}<p class="px-2.5 py-3 text-xs text-app-muted">
					You have no organization memberships.
				</p>{/each}
			{#if isAdmin}<a
					href={resolve('/admin?tab=organizations')}
					onclick={closeMenus}
					class="mt-1 flex items-center gap-2 border-t border-app-line px-2.5 py-3 text-sm text-brand-strong"
					><Plus size={15} /> Manage organizations</a
				>{/if}
		</div>
	</details>
	<span aria-hidden="true" class="text-app-muted">/</span>
	<details class="min-w-0" bind:this={catalogMenu}>
		<summary
			class="flex h-9 cursor-pointer list-none items-center gap-2 rounded-md border border-app-line bg-app-card px-2 text-sm hover:border-app-line-strong [&::-webkit-details-marker]:hidden"
			aria-label="Switch catalog"
			title={selectedCatalog || 'Select catalog'}
		>
			<Database size={16} class="shrink-0 text-app-muted" />
			<span class="hidden max-w-40 truncate xl:block">{selectedCatalog || 'Catalog'}</span>
			<ChevronsUpDown size={13} class="shrink-0 text-app-muted" />
		</summary>
		<div
			class="absolute right-0 top-11 z-50 max-h-[70dvh] w-[min(288px,80vw)] overflow-y-auto rounded-lg border border-app-line bg-app-raised p-1.5 shadow-[var(--shadow-popover)]"
		>
			<p class="break-words px-2.5 py-2 text-xs font-semibold text-app-muted">
				Catalogs in {current?.name ?? 'your organization'}
			</p>
			{#each catalogs as catalog (catalog.name)}
				<a
					href={resolve(browseHref(catalog.name))}
					onclick={closeMenus}
					aria-current={catalog.name === selectedCatalog ? 'true' : undefined}
					class="flex min-w-0 items-center gap-2 rounded-md px-2.5 py-2 hover:bg-app-sidebar-hover"
				>
					<span class="min-w-0 flex-1"
						><span class="block break-all text-sm font-medium">{catalog.name}</span><span
							class="block text-xs text-app-muted"
							>{catalog.storageConfigInfo.storageType} storage</span
						></span
					>
					{#if catalog.name === selectedCatalog}<Check
							size={16}
							class="shrink-0 text-brand-strong"
						/>{/if}
				</a>
			{:else}<p class="px-2.5 py-3 text-xs text-app-muted">
					No accessible catalogs in this organization.
				</p>{/each}
		</div>
	</details>
</div>
