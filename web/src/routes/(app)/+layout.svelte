<script lang="ts">
	import type { NavigationTarget } from '@sveltejs/kit';
	import { afterNavigate } from '$app/navigation';
	import { asset, resolve } from '$app/paths';
	import { navigating, page } from '$app/state';
	import {
		BookOpen,
		Boxes,
		FileJson,
		PanelLeft,
		Search as SearchIcon,
		UserRound
	} from '@lucide/svelte';
	import { onMount } from 'svelte';
	import AccountMenu from '$design/components/AccountMenu.svelte';
	import OrganizationSwitcher from '$design/components/OrganizationSwitcher.svelte';
	import SiteSearch from '$design/components/SiteSearch.svelte';
	import ThemeToggle from '$design/components/ThemeToggle.svelte';
	import { DOCS_PATH } from '$lib/docs';
	import { organizationCookie } from '$lib/organization-cookie';
	import { visibleOrganization } from '$lib/organizations';
	import { setShellOrganization } from '$lib/shell';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	/** How long a navigation may take before the loading bar shows. */
	const LOADING_DELAY_MS = 200;
	/** No preference follows the viewport; an explicit choice lasts across visits. */
	let sidebarCollapsed = $state<boolean | null>(null);
	let wideViewport = $state(false);
	let mounted = $state(false);
	/** Animate user choices without sliding the saved preference into place on load. */
	let animateSidebar = $state(false);
	const sidebarPinned = $derived(sidebarCollapsed === null ? wideViewport : !sidebarCollapsed);
	let sidebarPreview = $state(false);
	const sidebarVisible = $derived(sidebarPinned || sidebarPreview);
	const automatic = $derived(sidebarCollapsed === null);
	let sidebar = $state<HTMLElement>();
	let sidebarToggle = $state<HTMLButtonElement>();
	let pointerOnToggle = false;
	let pointerInSidebar = false;
	let previewCloseTimer: ReturnType<typeof setTimeout> | undefined;

	onMount(() => {
		const viewport = window.matchMedia?.('(min-width: 1280px)');
		const updateViewport = () => (wideViewport = viewport?.matches ?? false);
		updateViewport();
		viewport?.addEventListener('change', updateViewport);
		try {
			const saved = localStorage.getItem('huron-sidebar-collapsed');
			if (saved === 'true' || saved === 'false') sidebarCollapsed = saved === 'true';
		} catch {
			// Navigation still works when the browser does not allow preference storage.
		}
		mounted = true;
		return () => {
			viewport?.removeEventListener('change', updateViewport);
			clearTimeout(previewCloseTimer);
		};
	});

	function toggleSidebar() {
		animateSidebar = true;
		sidebarCollapsed = sidebarPinned;
		sidebarPreview = false;
		clearTimeout(previewCloseTimer);
		try {
			localStorage.setItem('huron-sidebar-collapsed', String(sidebarCollapsed));
		} catch {
			// Keep the choice for this visit even when it cannot be saved.
		}
	}

	function previewSidebar(event: PointerEvent) {
		if (event.pointerType !== 'mouse') return;
		pointerOnToggle = true;
		clearTimeout(previewCloseTimer);
		if (sidebarPinned) return;
		animateSidebar = true;
		sidebarPreview = true;
	}

	/** Leave time to cross from the toolbar toggle into the floating navigation. */
	function schedulePreviewClose() {
		clearTimeout(previewCloseTimer);
		previewCloseTimer = setTimeout(() => {
			if (!pointerOnToggle && !pointerInSidebar && !sidebar?.contains(document.activeElement)) {
				sidebarPreview = false;
			}
		}, 120);
	}

	function dismissPreview(event: KeyboardEvent) {
		if (event.key !== 'Escape' || !sidebarPreview) return;
		sidebarPreview = false;
		clearTimeout(previewCloseTimer);
		sidebarToggle?.focus();
	}

	/** The page's organization (`page.data.organization`) once it is one the user can see. */
	const pageOrganization = $derived(
		visibleOrganization(page.data.organization, data.organizations)
	);
	/**
	 * The organization the browser remembers: the one this shell last wrote to the cookie, else
	 * the cookie as the server read it when the shell loaded.
	 */
	let written = $state<string | null>(null);
	const remembered = $derived(
		visibleOrganization(written ?? data.rememberedOrganization, data.organizations)
	);
	/** An error page names no organization, having no data of its own: it keeps the remembered one. */
	const current = $derived(page.data.organization === undefined ? remembered : pageOrganization);
	setShellOrganization(() => current);
	const routeId = $derived(page.route.id ?? '');
	/** Catalog pages share an edge-to-edge workspace with their explorer. */
	const workspace = $derived(
		routeId.startsWith('/(app)/catalogs/') && page.data.catalog !== undefined
	);

	/**
	 * The search pages: a catalog's, an organization's and the one that asks which organization.
	 * They belong to searching, not to the Catalog section the first two sit under.
	 */
	const SEARCH_ROUTES: readonly string[] = [
		'/(app)/catalogs/[catalog=segment]/(overview)/search',
		'/(app)/orgs/[org=segment]/search',
		'/(app)/search'
	];
	const searching = $derived(SEARCH_ROUTES.includes(routeId));
	const schemas = $derived(routeId.startsWith('/(app)/schemas'));

	/** A link of the primary navigation. */
	interface NavigationItem {
		label: string;
		href: string;
		icon: typeof Boxes;
		inSection: boolean;
		/** Whether the browser loads the page itself, as for the documentation, which no route holds. */
		reload?: boolean;
	}

	const navigation: NavigationItem[] = $derived([
		{
			label: 'Catalog',
			href: current
				? resolve('/(app)/orgs/[org=segment]', { org: current.name })
				: resolve('/orgs'),
			icon: Boxes,
			inSection:
				!searching &&
				(routeId === '/(app)' ||
					routeId.startsWith('/(app)/orgs') ||
					routeId.startsWith('/(app)/catalogs'))
		},
		{ label: 'Search', href: resolve('/(app)/search'), icon: SearchIcon, inSection: searching },
		{ label: 'Schemas', href: resolve('/(app)/schemas'), icon: FileJson, inSection: schemas }
	]);
	/** The public documentation: never a section of this app, so never current. */
	const docs: NavigationItem = {
		label: 'Docs',
		href: DOCS_PATH,
		icon: BookOpen,
		inSection: false,
		reload: true
	};
	const account: NavigationItem = $derived({
		label: 'Account',
		href: resolve('/account'),
		icon: UserRound,
		inSection: routeId === '/(app)/account'
	});

	/**
	 * A navigation link is the current page only when it leads to this very page; elsewhere in its
	 * section (Catalog leads to one organization while all of them show) it marks the section.
	 * The server writes links relative to the page (`../../orgs/helio`), so the link is resolved
	 * against the page's address before the two are compared.
	 */
	function ariaCurrent(item: { href: string; inSection: boolean }): 'page' | 'true' | undefined {
		if (!item.inSection) return undefined;
		return new URL(item.href, page.url).pathname === page.url.pathname ? 'page' : 'true';
	}

	/** The navigation that has taken longer than the delay; raw, to compare it by identity. */
	let slowNavigation = $state.raw<NavigationTarget | null>(null);
	const slow = $derived(navigating.to !== null && navigating.to === slowNavigation);

	$effect(() => {
		const target = navigating.to;
		if (target === null) return;
		const timer = setTimeout(() => (slowNavigation = target), LOADING_DELAY_MS);
		return () => clearTimeout(timer);
	});

	// The browser remembers the organization, never a load: preloads would change it on hover.
	afterNavigate(() => {
		if (pageOrganization === null) return;
		written = pageOrganization.name;
		document.cookie = organizationCookie(pageOrganization.name, location.protocol === 'https:');
	});
</script>

{#snippet logo()}
	<!-- Absolute URLs stay valid when this layout survives navigation to a deeper route. -->
	<img
		src={new URL(asset('/huron-mark.svg'), page.url).href}
		alt=""
		width="32"
		height="32"
		class="size-8 shrink-0 dark:hidden"
	/>
	<img
		src={new URL(asset('/huron-mark-dark.svg'), page.url).href}
		alt=""
		width="32"
		height="32"
		class="hidden size-8 shrink-0 dark:block"
	/>
{/snippet}

<svelte:window onkeydown={dismissPreview} />

<a class="skip-link" href="#main">Skip to content</a>
{#if slow}
	<div class="fixed inset-x-0 top-0 z-50 h-0.5 overflow-hidden" aria-hidden="true">
		<div
			class="h-full w-1/3 animate-loading bg-brand motion-reduce:w-full motion-reduce:animate-none"
		></div>
	</div>
{/if}
<p role="status" class="sr-only">{slow ? 'Loading…' : ''}</p>

<div class="min-h-dvh bg-app-sidebar text-app-fg">
	<aside
		bind:this={sidebar}
		id="application-sidebar"
		aria-label="Sidebar"
		aria-hidden={mounted && !sidebarVisible ? true : undefined}
		inert={mounted && !sidebarVisible}
		onpointerenter={() => {
			pointerInSidebar = true;
			clearTimeout(previewCloseTimer);
		}}
		onpointerleave={() => {
			pointerInSidebar = false;
			schedulePreviewClose();
		}}
		onfocusout={schedulePreviewClose}
		class={[
			'fixed top-16 bottom-1 left-workspace-gap z-30 hidden w-sidebar flex-col bg-app-sidebar no-js:visible no-js:translate-x-0 md:flex',
			animateSidebar &&
				'transition-[translate,visibility] duration-200 ease-in-out motion-reduce:transition-none',
			sidebarVisible
				? 'visible translate-x-0'
				: 'invisible -translate-x-[calc(100%+var(--spacing-workspace-gap))]',
			automatic && !mounted && 'xl:visible xl:translate-x-0',
			sidebarPreview &&
				!sidebarPinned &&
				'rounded-lg shadow-menu inset-ring-[0.5px] inset-ring-app-muted/60 dark:inset-ring-white/40'
		]}
	>
		<nav aria-label="Primary" class="grid gap-1 p-2">
			{#each navigation as item (item.label)}
				{@render sidebarLink(item)}
			{/each}
		</nav>
		<div class="mt-auto grid gap-1 p-2">
			{@render sidebarLink(docs)}
			{@render sidebarLink(account)}
			<p class="m-0 flex items-start gap-2 px-3 py-2 text-xs text-app-muted">
				<span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden="true"
				></span>Read-only · changes are made with the huron CLI
			</p>
		</div>
	</aside>

	<!-- The full-width toolbar and navigation share one uninterrupted shell surface. -->
	<header
		class="fixed inset-x-0 top-0 z-40 flex h-16 items-center gap-2 bg-app-sidebar px-3 sm:px-4 md:grid md:grid-cols-[auto_minmax(0,1fr)_auto] md:gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)_minmax(0,1fr)]"
	>
		<div class="flex shrink-0 items-center gap-2.5 md:w-44 lg:w-56">
			{#if mounted}
				<button
					bind:this={sidebarToggle}
					type="button"
					onclick={toggleSidebar}
					onpointerenter={previewSidebar}
					onpointerleave={() => {
						pointerOnToggle = false;
						schedulePreviewClose();
					}}
					aria-label={sidebarPinned ? 'Collapse sidebar' : 'Expand sidebar'}
					title={sidebarPinned ? 'Collapse sidebar' : 'Expand sidebar'}
					aria-expanded={sidebarVisible}
					aria-controls="application-sidebar"
					class="hidden size-7 shrink-0 place-items-center rounded-sm border border-transparent text-app-muted hover:border-app-line hover:bg-app-sidebar-hover hover:text-app-fg md:grid"
				>
					<PanelLeft size={16} aria-hidden="true" />
				</button>
			{/if}
			<a
				href={resolve('/')}
				class="flex min-w-0 items-center gap-2.5 rounded-md text-lg font-semibold text-app-fg no-underline"
			>
				{@render logo()}<span class="sr-only md:not-sr-only">Huron</span>
			</a>
		</div>
		<div class="hidden min-w-0 md:flex md:justify-center">
			<!-- Keep the text of a submitted search, without carrying unsubmitted text to another page. -->
			{#key page.url.pathname + page.url.search}
				<SiteSearch action={resolve('/(app)/search')} name={null} q={page.data.search?.q ?? ''} />
			{/key}
		</div>
		<div class="ml-auto flex min-w-0 items-center justify-end gap-2 md:ml-0">
			<OrganizationSwitcher
				organizations={data.organizations}
				{current}
				unavailable={data.organizationsUnavailable}
			/>
			<ThemeToggle />
			<AccountMenu user={data.user} />
		</div>
	</header>

	<main
		id="main"
		tabindex="-1"
		aria-busy={navigating.to ? 'true' : undefined}
		class={[
			'min-h-dvh pt-16 pb-20 md:pb-0',
			animateSidebar &&
				'transition-[padding-left] duration-200 ease-in-out motion-reduce:transition-none',
			sidebarPinned ? 'md:pl-sidebar-offset' : 'md:pl-0',
			automatic && !mounted && 'xl:pl-sidebar-offset',
			'no-js:md:pl-sidebar-offset'
		]}
	>
		<div class={workspace ? 'w-full min-w-0' : 'w-full p-2'}>
			{#if workspace}
				{@render children()}
			{:else}
				<div class="min-h-workspace rounded-card bg-app-card">
					<div class="mx-auto max-w-shell p-4 sm:p-6 lg:p-8">{@render children()}</div>
				</div>
			{/if}
		</div>
	</main>

	<!-- The padding below the links leaves room for their focus rings above the screen's edge. -->
	<nav
		aria-label="Primary"
		class="fixed inset-x-0 bottom-0 z-30 grid auto-cols-fr grid-flow-col border-t border-app-line bg-app-card px-1 pb-1 md:hidden"
	>
		{#each [...navigation, docs, account] as item (item.label)}
			<a
				href={item.href}
				aria-current={ariaCurrent(item)}
				data-sveltekit-reload={item.reload || undefined}
				class={[
					'relative flex flex-col items-center gap-1 px-1 py-2 text-xs no-underline',
					item.inSection ? 'font-semibold text-brand-strong' : 'font-medium text-app-muted'
				]}
			>
				{#if item.inSection}
					<span
						class="absolute -top-px left-1/2 w-12 -translate-x-1/2 border-t-2 border-brand-strong"
						aria-hidden="true"
					></span>
				{/if}
				{@render linkContent(item)}
			</a>
		{/each}
	</nav>
</div>

<!--
	A navigation link's icon and label. The current section's are heavier and its link has a bar,
	so it stands out by more than color, in grayscale too. The bar is a border, which forced colors
	keep; they drop fills, such as the sidebar's.
-->
{#snippet linkContent(item: NavigationItem, iconSize = 18)}
	{@const Icon = item.icon}
	<Icon
		class="shrink-0"
		size={iconSize}
		strokeWidth={item.inSection ? 2.3 : 1.9}
		aria-hidden="true"
	/>{item.label}
{/snippet}

<!-- Compact primary links keep their labels in both pinned and floating navigation. -->
{#snippet sidebarLink(item: NavigationItem)}
	<a
		href={item.href}
		aria-current={ariaCurrent(item)}
		data-sveltekit-reload={item.reload || undefined}
		class={[
			'relative flex min-h-7.5 items-center gap-1.5 rounded-md border border-transparent px-2 py-0.5 text-[13px]/5 no-underline',
			item.inSection
				? 'bg-brand-soft font-semibold text-brand-strong'
				: 'font-medium text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg'
		]}
	>
		{#if item.inSection}
			<span class="absolute inset-y-1.5 -left-1 border-l-2 border-brand-strong" aria-hidden="true"
			></span>
		{/if}
		{@render linkContent(item, 15)}
	</a>
{/snippet}
