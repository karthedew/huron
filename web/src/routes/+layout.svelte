<script lang="ts">
	import '$design/app.css';
	import { page } from '$app/state';
	import {
		Bell,
		BookOpen,
		Boxes,
		CircleHelp,
		FolderCog,
		Gauge,
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
	let mobileOpen = $state(false);
	let sidebarCollapsed = $state(false);
	let railDialog: HTMLDialogElement;

	onMount(() => {
		sidebarCollapsed = localStorage.getItem('huron-sidebar-collapsed') === 'true';
	});

	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
		localStorage.setItem('huron-sidebar-collapsed', String(sidebarCollapsed));
	}

	const primary = [
		{ href: '/', label: 'Catalog', icon: Boxes },
		{ href: '/browse', label: 'Browse', icon: BookOpen },
		{ href: '/ingestion', label: 'Ingestion', icon: UploadCloud },
		{ href: '/queue', label: 'Jobs & queue', icon: Gauge }
	];
	const manage = [
		{ href: '/settings/organization', label: 'Organization', icon: Settings },
		{ href: '/settings/project', label: 'Project settings', icon: FolderCog },
		{ href: '/admin', label: 'Admin', icon: ShieldCheck }
	];

	const isHere = (href: string) =>
		href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
</script>

<svelte:head>
	<meta name="theme-color" content="#00c7ad" />
	<meta
		name="description"
		content="Huron scientific lakehouse catalog, ingestion, and governance workspace."
	/>
</svelte:head>

<a class="skip-link" href="#main">Skip to content</a>

<div class="min-h-dvh bg-app-bg text-app-fg">
	<aside
		class={`fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-app-line bg-app-sidebar transition-[width] duration-200 md:flex ${sidebarCollapsed ? 'w-[68px]' : 'w-[68px] xl:w-[248px]'}`}
		aria-label="Application sidebar"
	>
		<div
			class={`relative flex h-16 items-center border-b border-app-line ${sidebarCollapsed ? 'justify-center px-2' : 'justify-center px-2 xl:justify-start xl:gap-2.5 xl:px-4'}`}
		>
			<button
				type="button"
				onclick={() => railDialog.showModal()}
				class="grid size-8 place-items-center rounded-md bg-brand text-sm font-black text-[#062d29] xl:hidden"
				aria-label="Expand navigation"
				title="Expand navigation">H</button
			>
			<span
				class="hidden size-8 place-items-center rounded-md bg-brand text-sm font-black text-[#062d29] xl:grid"
				>H</span
			>
			{#if !sidebarCollapsed}
				<span class="hidden text-[17px] font-semibold tracking-[-0.02em] xl:inline">Huron</span>
				<span
					class="hidden rounded bg-app-card px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-app-muted xl:inline"
					>Lakehouse</span
				>
				<button
					type="button"
					onclick={toggleSidebar}
					class="ml-auto hidden size-8 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg xl:grid"
					aria-label="Collapse sidebar"
					title="Collapse sidebar"
				>
					<PanelLeftClose size={17} />
				</button>
			{:else}
				<button
					type="button"
					onclick={toggleSidebar}
					class="absolute -right-3 top-5 hidden size-6 place-items-center rounded-full border border-app-line bg-app-card text-app-muted shadow-[var(--shadow-sm)] hover:border-app-line-strong hover:text-app-fg xl:grid"
					aria-label="Expand sidebar"
					title="Expand sidebar"
				>
					<PanelLeftOpen size={13} />
				</button>
			{/if}
		</div>

		<nav
			class={`flex min-h-0 flex-1 flex-col overflow-y-auto py-3 ${sidebarCollapsed ? 'px-2' : 'px-2 xl:px-2.5'}`}
			aria-label="Primary navigation"
		>
			{#if !sidebarCollapsed}
				<p
					class="hidden px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-app-muted xl:block"
				>
					Workspace
				</p>
			{/if}
			{#each primary as item}
				{@const Icon = item.icon}
				<a
					href={item.href}
					class={`mb-0.5 flex items-center rounded-md py-2 text-[13px] font-medium transition ${sidebarCollapsed ? 'justify-center px-2' : 'justify-center px-2 xl:justify-start xl:gap-2.5 xl:px-2.5'}`}
					class:bg-brand-soft={isHere(item.href)}
					class:text-brand-strong={isHere(item.href)}
					class:text-app-muted={!isHere(item.href)}
					class:hover:bg-app-sidebar-hover={!isHere(item.href)}
					class:hover:text-app-fg={!isHere(item.href)}
					aria-current={isHere(item.href) ? 'page' : undefined}
					aria-label={item.label}
					title={item.label}
				>
					<Icon size={17} strokeWidth={isHere(item.href) ? 2.3 : 1.9} />
					{#if !sidebarCollapsed}<span class="hidden xl:inline">{item.label}</span>{/if}
				</a>
			{/each}

			{#if !sidebarCollapsed}
				<p
					class="mt-5 hidden px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-app-muted xl:block"
				>
					Manage
				</p>
			{/if}
			<div
				class={`mx-2 my-3 border-t border-app-line ${sidebarCollapsed ? '' : 'xl:hidden'}`}
			></div>
			{#each manage as item}
				{@const Icon = item.icon}
				<a
					href={item.href}
					class={`mb-0.5 flex items-center rounded-md py-2 text-[13px] font-medium transition ${sidebarCollapsed ? 'justify-center px-2' : 'justify-center px-2 xl:justify-start xl:gap-2.5 xl:px-2.5'}`}
					class:bg-brand-soft={isHere(item.href)}
					class:text-brand-strong={isHere(item.href)}
					class:text-app-muted={!isHere(item.href)}
					class:hover:bg-app-sidebar-hover={!isHere(item.href)}
					class:hover:text-app-fg={!isHere(item.href)}
					aria-label={item.label}
					title={item.label}
				>
					<Icon size={17} strokeWidth={isHere(item.href) ? 2.3 : 1.9} />
					{#if !sidebarCollapsed}<span class="hidden xl:inline">{item.label}</span>{/if}
				</a>
			{/each}
		</nav>

		<div class={`border-t border-app-line ${sidebarCollapsed ? 'p-2' : 'p-2 xl:p-2.5'}`}>
			<a
				href="/account"
				class={`flex items-center rounded-md py-2 text-[13px] font-medium text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg ${sidebarCollapsed ? 'justify-center px-2' : 'justify-center px-2 xl:justify-start xl:gap-2.5 xl:px-2.5'}`}
				aria-label="Help and account"
				title="Help and account"
			>
				<CircleHelp size={17} />
				{#if !sidebarCollapsed}<span class="hidden xl:inline">Help & account</span>{/if}
			</a>
			{#if !sidebarCollapsed}
				<div class="mt-1 hidden items-center gap-2 px-2.5 py-2 text-[11px] text-app-muted xl:flex">
					<span class="size-1.5 rounded-full bg-brand"></span>
					Fixture workspace · API pending
				</div>
			{/if}
		</div>
	</aside>

	<dialog
		bind:this={railDialog}
		aria-label="Expanded navigation"
		class="fixed inset-y-0 left-0 z-50 m-0 hidden h-dvh max-h-none w-[288px] max-w-none flex-col border-0 border-r border-app-line bg-app-sidebar p-0 text-app-fg shadow-[var(--shadow-popover)] open:flex xl:open:hidden backdrop:bg-black/45"
	>
		<div class="flex h-16 items-center gap-2.5 border-b border-app-line px-4">
			<span
				class="grid size-8 place-items-center rounded-md bg-brand text-sm font-black text-[#062d29]"
				>H</span
			>
			<span class="text-[17px] font-semibold tracking-[-0.02em]">Huron</span>
			<span
				class="rounded bg-app-card px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-app-muted"
				>Lakehouse</span
			>
			<button
				type="button"
				onclick={() => railDialog.close()}
				class="ml-auto grid size-8 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
				aria-label="Close expanded navigation"><X size={17} /></button
			>
		</div>
		<nav
			class="flex min-h-0 flex-1 flex-col overflow-y-auto px-2.5 py-3"
			aria-label="Expanded primary navigation"
		>
			<p class="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-app-muted">
				Workspace
			</p>
			{#each primary as item}
				{@const Icon = item.icon}
				<a
					href={item.href}
					onclick={() => railDialog.close()}
					class="mb-0.5 flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium transition"
					class:bg-brand-soft={isHere(item.href)}
					class:text-brand-strong={isHere(item.href)}
					class:text-app-muted={!isHere(item.href)}
					class:hover:bg-app-sidebar-hover={!isHere(item.href)}
					class:hover:text-app-fg={!isHere(item.href)}
					aria-current={isHere(item.href) ? 'page' : undefined}
					><Icon size={17} strokeWidth={isHere(item.href) ? 2.3 : 1.9} />{item.label}</a
				>
			{/each}
			<p
				class="mt-5 px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-app-muted"
			>
				Manage
			</p>
			{#each manage as item}
				{@const Icon = item.icon}
				<a
					href={item.href}
					onclick={() => railDialog.close()}
					class="mb-0.5 flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium transition"
					class:bg-brand-soft={isHere(item.href)}
					class:text-brand-strong={isHere(item.href)}
					class:text-app-muted={!isHere(item.href)}
					class:hover:bg-app-sidebar-hover={!isHere(item.href)}
					class:hover:text-app-fg={!isHere(item.href)}
					><Icon size={17} strokeWidth={isHere(item.href) ? 2.3 : 1.9} />{item.label}</a
				>
			{/each}
		</nav>
		<div class="border-t border-app-line p-2.5">
			<a
				href="/account"
				onclick={() => railDialog.close()}
				class="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
				><CircleHelp size={17} /> Help & account</a
			>
		</div>
	</dialog>

	<header
		class={`fixed inset-x-0 top-0 z-30 flex h-16 items-center border-b border-app-line bg-app-bg/95 px-3 backdrop-blur transition-[left] duration-200 md:left-[68px] md:px-6 ${sidebarCollapsed ? '' : 'xl:left-[248px]'}`}
	>
		<button
			type="button"
			onclick={() => (mobileOpen = !mobileOpen)}
			class="mr-2 grid size-9 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover md:hidden"
			aria-label="Toggle navigation"
		>
			<PanelLeft size={19} />
		</button>
		<form
			action="/"
			method="GET"
			role="search"
			class="mx-auto hidden w-full max-w-xl sm:block md:mx-0"
		>
			<label class="relative block">
				<span class="visually-hidden">Search catalog</span>
				<Search
					size={16}
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
				/>
				<input
					name="q"
					type="search"
					placeholder="Search datasets, releases, or products…"
					class="h-9 w-full rounded-md border border-app-line bg-app-card pl-9 pr-16 text-[13px] text-app-fg outline-none transition placeholder:text-app-muted focus:border-brand-strong"
				/>
				<kbd
					class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-app-line bg-app-bg px-1.5 py-0.5 text-[10px] text-app-muted"
					>⌘ K</kbd
				>
			</label>
		</form>
		<div class="ml-auto flex items-center gap-2 sm:pl-5">
			<WorkspaceSwitcher organizations={data.organizations} toolbar align="right" />
			<ThemeToggle />
			<button
				type="button"
				class="relative grid size-9 place-items-center rounded-md border border-app-line bg-app-card text-app-muted hover:text-app-fg"
				aria-label="Notifications"
			>
				<Bell size={17} />
				<span class="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-brand"></span>
			</button>
			<AccountMenu user={data.user} />
		</div>
	</header>

	{#if mobileOpen}
		<button
			class="fixed inset-0 z-40 bg-black/35 md:hidden"
			aria-label="Close navigation"
			onclick={() => (mobileOpen = false)}
		></button>
		<aside
			class="fixed inset-y-0 left-0 z-50 w-[280px] border-r border-app-line bg-app-sidebar p-3 md:hidden"
		>
			<div class="mb-4 flex items-center gap-2.5 px-2 py-2">
				<span
					class="grid size-8 place-items-center rounded-md bg-brand text-sm font-black text-[#062d29]"
					>H</span
				>
				<span class="text-lg font-semibold">Huron</span>
			</div>
			<nav class="grid gap-1">
				{#each [...primary, ...manage] as item}
					{@const Icon = item.icon}
					<a
						href={item.href}
						onclick={() => (mobileOpen = false)}
						class="flex items-center gap-3 rounded-md px-3 py-2.5 text-sm text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg"
					>
						<Icon size={18} />
						{item.label}
					</a>
				{/each}
			</nav>
		</aside>
	{/if}

	<main
		id="main"
		class={`min-h-dvh pt-16 transition-[padding] duration-200 md:pl-[68px] ${sidebarCollapsed ? '' : 'xl:pl-[248px]'}`}
	>
		<div class="mx-auto w-full max-w-[1540px] px-4 py-6 pb-24 sm:px-6 lg:px-8 lg:py-8">
			{@render children()}
		</div>
	</main>

	<nav
		class="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-app-line bg-app-card px-1 pb-[env(safe-area-inset-bottom)] md:hidden"
		aria-label="Mobile navigation"
	>
		{#each primary.slice(0, 4) as item}
			{@const Icon = item.icon}
			<a
				href={item.href}
				class="flex flex-col items-center gap-1 px-1 py-2 text-[10px] font-medium"
				class:text-brand-strong={isHere(item.href)}
				class:text-app-muted={!isHere(item.href)}
			>
				<Icon size={18} />
				{item.label.split(' ')[0]}
			</a>
		{/each}
	</nav>
</div>
