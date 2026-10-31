<script lang="ts">
	import type { NavigationTarget } from '@sveltejs/kit';
	import { afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { navigating, page } from '$app/state';
	import { Boxes, Search as SearchIcon, UserRound } from '@lucide/svelte';
	import AccountMenu from '$design/components/AccountMenu.svelte';
	import OrganizationSwitcher from '$design/components/OrganizationSwitcher.svelte';
	import SiteSearch from '$design/components/SiteSearch.svelte';
	import ThemeToggle from '$design/components/ThemeToggle.svelte';
	import { organizationCookie } from '$lib/organization-cookie';
	import { visibleOrganization } from '$lib/organizations';
	import { searchScope } from '$lib/search-links';
	import { setShellOrganization } from '$lib/shell';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	/** How long a navigation may take before the loading bar shows. */
	const LOADING_DELAY_MS = 200;

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

	/**
	 * The search pages: a catalog's, an organization's and the one that asks which organization.
	 * They belong to searching, not to the Catalogs section the first two sit under.
	 */
	const SEARCH_ROUTES: readonly string[] = [
		'/(app)/catalogs/[catalog=segment]/(overview)/search',
		'/(app)/orgs/[org=segment]/search',
		'/(app)/search'
	];
	const searching = $derived(SEARCH_ROUTES.includes(routeId));
	/** What the search box and Search search: this catalog, else the organization, else ask. */
	const scope = $derived(searchScope(page.data.catalog, current));

	const navigation = $derived([
		{
			label: 'Catalogs',
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
		{ label: 'Search', href: scope.href, icon: SearchIcon, inSection: searching }
	]);
	const account = $derived({
		label: 'Account',
		href: resolve('/account'),
		icon: UserRound,
		inSection: routeId === '/(app)/account'
	});

	/**
	 * A navigation link is the current page only when it leads to this very page; elsewhere in its
	 * section (Catalogs leads to one organization while all of them show) it marks the section.
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
	<span
		class="grid size-8 shrink-0 place-items-center rounded-md bg-brand text-sm font-black text-brand-ink"
		aria-hidden="true">H</span
	>
{/snippet}

<a class="skip-link" href="#main">Skip to content</a>
{#if slow}
	<div class="fixed inset-x-0 top-0 z-50 h-0.5 overflow-hidden" aria-hidden="true">
		<div
			class="h-full w-1/3 animate-loading bg-brand motion-reduce:w-full motion-reduce:animate-none"
		></div>
	</div>
{/if}
<p role="status" class="sr-only">{slow ? 'Loading…' : ''}</p>

<div class="min-h-dvh bg-app-bg text-app-fg">
	<aside
		aria-label="Sidebar"
		class="fixed inset-y-0 left-0 z-40 hidden w-rail flex-col border-r border-app-line bg-app-sidebar md:flex xl:w-sidebar"
	>
		<div
			class="flex h-16 shrink-0 items-center justify-center border-b border-app-line px-2 xl:justify-start xl:px-4"
		>
			<a
				href={resolve('/')}
				class="flex items-center gap-2.5 rounded-md text-lg font-semibold text-app-fg no-underline"
				>{@render logo()}<span class="sr-only xl:not-sr-only">Huron</span></a
			>
		</div>
		<nav aria-label="Primary" class="grid gap-1 p-1.5 xl:p-2.5">
			{#each navigation as item (item.label)}
				{@render sidebarLink(item)}
			{/each}
		</nav>
		<div class="mt-auto grid gap-1 border-t border-app-line p-1.5 xl:p-2.5">
			{@render sidebarLink(account)}
			<p class="m-0 hidden items-start gap-2 px-2.5 py-2 text-xs text-app-muted xl:flex">
				<span class="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden="true"
				></span>Read-only · changes are made with the huron CLI
			</p>
		</div>
	</aside>

	<!-- Above the bottom navigation, which follows it, so an open menu is never covered. -->
	<header
		class="fixed inset-x-0 top-0 z-40 flex h-16 items-center gap-2 border-b border-app-line bg-app-bg/95 px-3 backdrop-blur sm:px-4 md:left-rail md:px-6 xl:left-sidebar"
	>
		<a href={resolve('/')} class="flex shrink-0 rounded-md no-underline md:hidden"
			>{@render logo()}<span class="sr-only">Huron</span></a
		>
		<!--
			Drawn afresh on each page: it holds the text of the search shown, not what was typed. A
			change of the fragment alone, as the skip link makes, stays on the page and keeps it.
		-->
		{#key page.url.pathname + page.url.search}
			<SiteSearch action={scope.href} name={scope.name} q={page.data.search?.q ?? ''} />
		{/key}
		<div class="ml-auto flex min-w-0 items-center gap-2">
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
		class="min-h-dvh pt-16 pb-20 md:pb-0 md:pl-rail xl:pl-sidebar"
	>
		<div class="mx-auto w-full max-w-shell px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
			{@render children()}
		</div>
	</main>

	<!-- The padding below the links leaves room for their focus rings above the screen's edge. -->
	<nav
		aria-label="Primary"
		class="fixed inset-x-0 bottom-0 z-30 grid auto-cols-fr grid-flow-col border-t border-app-line bg-app-card px-1 pb-1 md:hidden"
	>
		{#each [...navigation, account] as item (item.label)}
			<a
				href={item.href}
				aria-current={ariaCurrent(item)}
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
{#snippet linkContent(item: (typeof navigation)[number])}
	{@const Icon = item.icon}
	<Icon size={18} strokeWidth={item.inSection ? 2.3 : 1.9} aria-hidden="true" />{item.label}
{/snippet}

<!-- The rail stacks a short label under each icon (nothing hover-only); the sidebar sets it beside. -->
{#snippet sidebarLink(item: (typeof navigation)[number])}
	<a
		href={item.href}
		aria-current={ariaCurrent(item)}
		class={[
			'relative flex flex-col items-center gap-1 rounded-md px-0.5 py-2 text-xs no-underline xl:flex-row xl:gap-2.5 xl:px-2.5 xl:py-2.5 xl:text-sm',
			item.inSection
				? 'bg-brand-soft font-semibold text-brand-strong'
				: 'font-medium text-app-muted hover:bg-app-sidebar-hover hover:text-app-fg'
		]}
	>
		{#if item.inSection}
			<span
				class="absolute inset-y-2 -left-1.5 border-l-3 border-brand-strong xl:-left-2.5"
				aria-hidden="true"
			></span>
		{/if}
		{@render linkContent(item)}
	</a>
{/snippet}
