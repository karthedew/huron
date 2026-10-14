<script lang="ts">
	import '$design/app.css';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import {
		BookOpen,
		Boxes,
		CircleHelp,
		PanelLeft,
		PanelLeftClose,
		PanelLeftOpen,
		Search,
		Settings,
		ShieldCheck,
		UploadCloud,
		X
	} from '@lucide/svelte';
	import AccountMenu from '$design/components/AccountMenu.svelte';
	import ThemeToggle from '$design/components/ThemeToggle.svelte';
	import WorkspaceSwitcher from '$design/components/WorkspaceSwitcher.svelte';
	import type { LayoutData } from './$types';
	import { onMount } from 'svelte';

	let { data, children }: { data: LayoutData; children: import('svelte').Snippet } = $props();
	let sidebarCollapsed = $state(false);
	let navigationDialog = $state<HTMLDialogElement>();
	const isAuthPage = $derived(page.url.pathname === '/login' || page.url.pathname === '/signup');
	const isBrowsePage = $derived(page.url.pathname === '/browse');
	const primary = $derived([
		{
			href: data.selectedOrganization
				? (`/?organization=${encodeURIComponent(data.selectedOrganization)}` as const)
				: '/',
			path: '/',
			label: 'Catalogs',
			icon: Boxes
		},
		{
			href: data.selectedOrganization
				? (`/browse?organization=${encodeURIComponent(data.selectedOrganization)}` as const)
				: '/browse',
			path: '/browse',
			label: 'Browse',
			icon: BookOpen
		},
		{
			href: data.selectedOrganization
				? (`/ingestion?organization=${encodeURIComponent(data.selectedOrganization)}` as const)
				: '/ingestion',
			path: '/ingestion',
			label: 'Ingestion',
			icon: UploadCloud
		}
	] as const);
	const manage = $derived([
		{
			href: data.selectedOrganization
				? (`/settings/organization?organization=${encodeURIComponent(data.selectedOrganization)}` as const)
				: ('/settings/organization' as const),
			path: '/settings/organization',
			label: 'Organization settings',
			icon: Settings
		},
		{
			href: data.selectedOrganization
				? (`/settings/catalog?organization=${encodeURIComponent(data.selectedOrganization)}${data.selectedCatalog ? `&catalog=${encodeURIComponent(data.selectedCatalog)}` : ''}` as const)
				: ('/settings/catalog' as const),
			path: '/settings/catalog',
			label: 'Catalog settings',
			icon: Settings
		},
		...(data.user?.isAdmin
			? [
					{
						href: data.selectedOrganization
							? (`/admin?organization=${encodeURIComponent(data.selectedOrganization)}` as const)
							: ('/admin' as const),
						path: '/admin',
						label: 'Administration',
						icon: ShieldCheck
					}
				]
			: [])
	]);
	const isHere = (path: string) =>
		path === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(path);

	onMount(() => {
		sidebarCollapsed = localStorage.getItem('huron-sidebar-collapsed') === 'true';
	});
	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
		localStorage.setItem('huron-sidebar-collapsed', String(sidebarCollapsed));
	}
</script>

<svelte:head>
	<meta name="theme-color" content="#00c7ad" />
	<meta
		name="description"
		content="Huron workspace for organizations, Polaris catalogs and scientific datasets."
	/>
</svelte:head>

{#snippet navigation(expanded: boolean)}
	<nav
		class="grid gap-1 p-2.5"
		aria-label={expanded ? 'Expanded primary navigation' : 'Primary navigation'}
	>
		{#each primary as item (item.path)}
			{@const Icon = item.icon}
			<a
				href={resolve(item.href)}
				onclick={() => navigationDialog?.close()}
				aria-current={isHere(item.path) ? 'page' : undefined}
				aria-label={item.label}
				title={item.label}
				class={[
					'flex items-center rounded-md py-2.5 text-[13px] font-medium',
					expanded
						? 'gap-2.5 px-2.5'
						: sidebarCollapsed
							? 'justify-center px-2'
							: 'justify-center px-2 xl:justify-start xl:gap-2.5 xl:px-2.5',
					isHere(item.path)
						? 'bg-brand-soft text-brand-strong'
						: 'text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg'
				]}
			>
				<Icon size={18} strokeWidth={isHere(item.path) ? 2.3 : 1.9} />
				{#if expanded}<span>{item.label}</span>{:else if !sidebarCollapsed}<span
						class="hidden xl:inline">{item.label}</span
					>{/if}
			</a>
		{/each}
		<div class="mx-2 my-3 border-t border-app-line"></div>
		{#each manage as item (item.path)}
			{@const Icon = item.icon}
			<a
				href={resolve(item.href)}
				onclick={() => navigationDialog?.close()}
				aria-current={isHere(item.path) ? 'page' : undefined}
				aria-label={item.label}
				title={item.label}
				class={[
					'flex items-center rounded-md py-2.5 text-[13px] font-medium',
					expanded
						? 'gap-2.5 px-2.5'
						: sidebarCollapsed
							? 'justify-center px-2'
							: 'justify-center px-2 xl:justify-start xl:gap-2.5 xl:px-2.5',
					isHere(item.path)
						? 'bg-brand-soft text-brand-strong'
						: 'text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg'
				]}
			>
				<Icon size={18} />
				{#if expanded}<span>{item.label}</span>{:else if !sidebarCollapsed}<span
						class="hidden xl:inline">{item.label}</span
					>{/if}
			</a>
		{/each}
	</nav>
{/snippet}

{#if isAuthPage}
	{@render children()}
{:else}
	<a class="skip-link" href="#main">Skip to content</a>
	<div class="min-h-dvh bg-app-bg text-app-fg">
		<aside
			class={`fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-app-line bg-app-sidebar transition-[width] duration-200 md:flex ${sidebarCollapsed ? 'w-[68px]' : 'w-[68px] xl:w-[248px]'}`}
			aria-label="Application sidebar"
		>
			<div
				class={`relative flex h-16 shrink-0 items-center border-b border-app-line px-2 ${sidebarCollapsed ? 'justify-center' : 'justify-center xl:justify-start xl:gap-2.5 xl:px-4'}`}
			>
				<button
					type="button"
					onclick={() => navigationDialog?.showModal()}
					class="grid size-8 place-items-center rounded-md bg-brand text-sm font-black text-[#062d29] xl:hidden"
					aria-label="Expand navigation"
					title="Expand navigation">H</button
				>
				<span
					class="hidden size-8 place-items-center rounded-md bg-brand text-sm font-black text-[#062d29] xl:grid"
					>H</span
				>
				{#if !sidebarCollapsed}<span class="hidden text-[17px] font-semibold xl:inline">Huron</span
					>{/if}
				<button
					type="button"
					onclick={toggleSidebar}
					class={[
						'hidden place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg xl:grid',
						sidebarCollapsed
							? 'absolute -right-3 top-5 size-6 border border-app-line bg-app-card'
							: 'ml-auto size-8'
					]}
					aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
					title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
				>
					{#if sidebarCollapsed}<PanelLeftOpen size={14} />{:else}<PanelLeftClose size={17} />{/if}
				</button>
			</div>
			<div class="min-h-0 flex-1 overflow-y-auto">{@render navigation(false)}</div>
			<div class="border-t border-app-line p-2.5">
				<a
					href={resolve(
						data.selectedOrganization
							? `/account?organization=${encodeURIComponent(data.selectedOrganization)}`
							: '/account'
					)}
					aria-label="Account settings"
					title="Account settings"
					class={[
						'flex items-center rounded-md py-2 text-[13px] font-medium text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg',
						sidebarCollapsed
							? 'justify-center px-2'
							: 'justify-center px-2 xl:justify-start xl:gap-2.5 xl:px-2.5'
					]}
					><CircleHelp size={17} />{#if !sidebarCollapsed}<span class="hidden xl:inline"
							>Account settings</span
						>{/if}</a
				>
				{#if !sidebarCollapsed}<p
						class="hidden items-center gap-2 px-2.5 py-2 text-[11px] text-app-muted xl:flex"
					>
						<span class="size-1.5 rounded-full bg-brand"></span>Raw · Iceberg · Icechunk
					</p>{/if}
			</div>
		</aside>
		<dialog
			bind:this={navigationDialog}
			aria-label="Expanded navigation"
			class="fixed inset-y-0 left-0 z-50 m-0 h-dvh max-h-none w-[min(288px,90vw)] border-0 border-r border-app-line bg-app-sidebar p-0 text-app-fg shadow-[var(--shadow-popover)] backdrop:bg-black/45"
		>
			<div class="flex h-16 items-center gap-2.5 border-b border-app-line px-4">
				<span
					class="grid size-8 place-items-center rounded-md bg-brand text-sm font-black text-[#062d29]"
					>H</span
				><span class="text-lg font-semibold">Huron</span><button
					type="button"
					onclick={() => navigationDialog?.close()}
					class="ml-auto grid size-8 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover"
					aria-label="Close expanded navigation"><X size={17} /></button
				>
			</div>
			{@render navigation(true)}
		</dialog>
		<header
			class={`fixed inset-x-0 top-0 z-30 flex h-16 items-center gap-2 border-b border-app-line bg-app-bg/95 px-3 backdrop-blur transition-[left] duration-200 md:left-[68px] md:px-6 ${sidebarCollapsed ? '' : 'xl:left-[248px]'}`}
		>
			<button
				type="button"
				onclick={() => navigationDialog?.showModal()}
				class="grid size-9 shrink-0 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover md:hidden"
				aria-label="Toggle navigation"><PanelLeft size={19} /></button
			>
			<form
				action={resolve('/')}
				method="GET"
				role="search"
				class="mr-auto hidden min-w-0 max-w-xl flex-1 md:block"
			>
				<label class="relative block"
					><span class="visually-hidden">Search catalog</span>{#if data.selectedOrganization}<input
							type="hidden"
							name="organization"
							value={data.selectedOrganization}
						/>{/if}<Search
						size={16}
						class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
					/><input
						name="q"
						type="search"
						placeholder="Search catalogs…"
						class="h-9 w-full rounded-md border border-app-line bg-app-card pl-9 pr-3 text-[13px] text-app-fg outline-none placeholder:text-app-muted focus:border-brand-strong"
					/></label
				>
			</form>
			<div class="ml-auto flex shrink-0 items-center gap-2">
				<WorkspaceSwitcher
					organizations={data.organizations}
					selectedOrganization={data.selectedOrganization}
					isAdmin={data.user?.isAdmin ?? false}
				/>
				<ThemeToggle />
				{#if data.user}<AccountMenu
						user={data.user}
						organization={data.selectedOrganization}
					/>{/if}
			</div>
		</header>
		<main
			id="main"
			class={`min-h-dvh pt-16 transition-[padding] duration-200 md:pl-[68px] ${sidebarCollapsed ? '' : 'xl:pl-[248px]'}`}
		>
			<div
				class={isBrowsePage
					? 'flex min-h-[calc(100dvh-64px)] w-full pb-16 md:pb-0'
					: 'mx-auto w-full max-w-[1540px] px-4 py-6 pb-24 sm:px-6 lg:px-8 lg:py-8'}
			>
				{@render children()}
			</div>
		</main>
		<nav
			class="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-app-line bg-app-card px-1 pb-[env(safe-area-inset-bottom)] md:hidden"
			aria-label="Mobile navigation"
		>
			{#each primary as item (item.path)}{@const Icon = item.icon}<a
					href={resolve(item.href)}
					aria-current={isHere(item.path) ? 'page' : undefined}
					class={[
						'flex flex-col items-center gap-1 px-1 py-2 text-[10px] font-medium',
						isHere(item.path) ? 'text-brand-strong' : 'text-app-muted'
					]}><Icon size={18} />{item.label}</a
				>{/each}
		</nav>
	</div>
{/if}
