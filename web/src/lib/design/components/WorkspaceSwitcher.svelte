<script lang="ts">
	import { Building2, Check, ChevronsUpDown, Plus } from '@lucide/svelte';
	import { selectedOrganization } from '$lib/stores/workspace';
	import type { Organization } from '$api/types';

	interface Props {
		organizations: Organization[];
		compact?: boolean;
		responsive?: boolean;
		toolbar?: boolean;
		align?: 'left' | 'right';
	}

	let {
		organizations,
		compact = false,
		responsive = false,
		toolbar = false,
		align = 'left'
	}: Props = $props();
	let menu: HTMLDetailsElement;
	const current = $derived(
		organizations.find((organization) => organization.slug === $selectedOrganization) ??
			organizations[0]
	);

	function choose(slug: string) {
		$selectedOrganization = slug;
		menu?.removeAttribute('open');
	}

	function closeFromOutside(event: MouseEvent) {
		if (menu?.hasAttribute('open') && !menu.contains(event.target as Node)) {
			menu.removeAttribute('open');
		}
	}

	function closeFromKeyboard(event: KeyboardEvent) {
		if (event.key === 'Escape') menu?.removeAttribute('open');
	}
</script>

<svelte:window onclick={closeFromOutside} onkeydown={closeFromKeyboard} />

<details class="group relative" bind:this={menu}>
	<summary
		class={`flex cursor-pointer list-none items-center gap-2 rounded-md border px-2 py-1.5 text-left transition [&::-webkit-details-marker]:hidden ${toolbar ? 'h-9 border-app-line bg-app-card hover:border-app-line-strong' : 'border-transparent hover:border-app-line hover:bg-app-card'}`}
		aria-label="Switch organization"
	>
		<span
			class="grid size-7 shrink-0 place-items-center rounded-md bg-brand-soft text-brand-strong"
		>
			<Building2 size={15} strokeWidth={2.2} />
		</span>
		{#if !compact}
			<span
				class={`min-w-0 flex-1 ${toolbar ? 'hidden max-w-40 lg:block' : responsive ? 'hidden xl:block' : ''}`}
			>
				{#if !toolbar}<span
						class="block text-[10px] font-semibold uppercase tracking-[0.09em] text-app-muted"
						>Organization</span
					>{/if}
				<span class="block truncate text-sm font-medium text-app-fg"
					>{current?.name ?? 'Select organization'}</span
				>
			</span>
		{/if}
		<ChevronsUpDown size={14} class="shrink-0 text-app-muted" />
	</summary>

	<div
		class={`absolute top-[calc(100%+0.45rem)] z-50 w-72 overflow-hidden rounded-lg border border-app-line bg-app-raised p-1.5 shadow-[var(--shadow-popover)] ${align === 'right' ? 'right-0' : 'left-0'}`}
	>
		<p
			class="px-2.5 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-app-muted"
		>
			Switch organization
		</p>
		{#each organizations as organization}
			<button
				type="button"
				onclick={() => choose(organization.slug)}
				class="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-app-sidebar-hover"
			>
				<span
					class="grid size-8 place-items-center rounded-md border border-app-line bg-app-card text-xs font-bold text-app-muted"
					>{organization.name.slice(0, 2).toUpperCase()}</span
				>
				<span class="min-w-0 flex-1">
					<span class="block truncate text-sm font-medium text-app-fg">{organization.name}</span>
					<span class="block truncate text-xs text-app-muted"
						>{organization.projectCount} projects</span
					>
				</span>
				{#if organization.slug === $selectedOrganization}<Check
						size={16}
						class="text-brand-strong"
					/>{/if}
			</button>
		{/each}
		<div class="my-1 border-t border-app-line"></div>
		<button
			type="button"
			class="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
		>
			<span
				class="grid size-8 place-items-center rounded-md border border-dashed border-app-line-strong"
				><Plus size={15} /></span
			>
			Create organization
		</button>
	</div>
</details>
