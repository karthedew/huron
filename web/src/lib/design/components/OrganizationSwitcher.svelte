<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Building2, Check, ChevronsUpDown } from '@lucide/svelte';
	import { displayName, secondaryName } from '$lib/names';
	import type { ShellOrganization } from '$lib/organizations';
	import { readSearch, searchQuery, sharedSearch } from '$lib/search';
	import { HeaderMenu } from './header-menu.svelte';

	interface Props {
		/** The organizations the user can see. */
		organizations: readonly ShellOrganization[];
		/** The current organization, when the user can see it. */
		current: ShellOrganization | null;
		/** The list could not be loaded. */
		unavailable: boolean;
	}

	let { organizations, current, unavailable }: Props = $props();

	const menu = new HeaderMenu();
	afterNavigate(menu.close);

	/** Pages below this route belong to one organization; switching keeps the page. */
	const ORGANIZATION_ROUTE = '/(app)/orgs/[org=segment]';

	/** The part of the current route below the organization (`''`, `/search`), if any. */
	const subRoute = $derived.by(() => {
		const id = page.route.id;
		if (id === null || !id.startsWith(ORGANIZATION_ROUTE)) return null;
		const rest = id.slice(ORGANIZATION_ROUTE.length);
		return rest === '' || (rest.startsWith('/') && !rest.includes('[')) ? rest : null;
	});

	/**
	 * The query kept with the sub-route: on an organization's search, that search as the page
	 * reads it, without its cursor (it belongs to the list it came from) and no longer than one of
	 * these links may repeat (`sharedSearch`: they are one per organization). Elsewhere none: the
	 * catalogs list reads only a cursor and a notice, which belong to the page that shows them.
	 */
	const keptQuery = $derived.by(() => {
		if (subRoute !== '/search') return '';
		const { search } = readSearch(page.url.searchParams, { drafts: true });
		return searchQuery(sharedSearch(search, organizations.length));
	});

	function href(organization: ShellOrganization): string {
		const overview = resolve(ORGANIZATION_ROUTE, { org: organization.name });
		return subRoute === null ? overview : `${overview}${subRoute}${keptQuery}`;
	}
</script>

<svelte:window onkeydown={menu.keydown} onclick={menu.clickOutside} />

{#if unavailable}
	<p class="m-0 flex h-9 min-w-0 items-center gap-1.5 text-xs text-app-muted sm:text-sm">
		<Building2 size={16} class="hidden shrink-0 sm:block" aria-hidden="true" />
		<span class="truncate">Organizations unavailable</span>
		<span aria-hidden="true">·</span>
		<a
			href={page.url.pathname + page.url.search}
			data-sveltekit-reload
			class="shrink-0 font-semibold">Try again</a
		>
	</p>
{:else if organizations.length === 0}
	<p class="m-0 flex h-9 min-w-0 items-center gap-2 text-sm text-app-muted">
		<Building2 size={16} class="shrink-0" aria-hidden="true" />
		<span class="truncate">No organizations</span>
	</p>
{:else if organizations.length === 1}
	<p class="m-0 flex h-9 min-w-0 items-center gap-2 text-sm">
		<Building2 size={16} class="shrink-0 text-brand-strong" aria-hidden="true" />
		<span class="sr-only">Organization: {displayName(organizations[0])}</span>
		<!-- Capped like the name in the switcher's summary; the link beside it keeps its own room. -->
		<span class="truncate font-medium sm:max-w-56 lg:max-w-64" aria-hidden="true"
			>{displayName(organizations[0])}</span
		>
		<span class="text-app-muted" aria-hidden="true">·</span>
		<a href={resolve('/orgs')} class="shrink-0 font-semibold whitespace-nowrap"
			>All<span class="sr-only sm:not-sr-only">{' '}organizations</span></a
		>
	</p>
{:else}
	<details
		bind:open={menu.open}
		bind:this={menu.details}
		onfocusout={menu.focusOut}
		class="relative min-w-0 sm:max-w-72 lg:max-w-80"
	>
		<summary
			class="no-marker flex h-9 min-w-0 cursor-pointer items-center gap-2 rounded-md border border-app-line bg-app-card px-2 text-sm text-app-fg hover:border-app-line-strong"
		>
			<Building2 size={16} class="shrink-0 text-brand-strong" aria-hidden="true" />
			{#if current}
				<!-- One phrase for screen readers; split spans would gain stray spaces in its name. -->
				<span class="sr-only">Organization: {displayName(current)}, switch</span>
				<span class="truncate font-medium" aria-hidden="true">{displayName(current)}</span>
			{:else}
				<span class="truncate">Choose organization</span>
			{/if}
			<ChevronsUpDown size={14} class="shrink-0 text-app-muted" aria-hidden="true" />
		</summary>
		<div
			class="absolute top-full right-0 z-50 mt-2 w-72 rounded-lg border border-app-line bg-app-raised p-1.5 shadow-menu max-sm:fixed max-sm:inset-x-3 max-sm:top-16 max-sm:w-auto"
		>
			<!-- Padding inside the scrolling list keeps the links' focus outlines from being cut off;
				the negative margin leaves the rows where they were. -->
			<ul
				aria-label="Organizations"
				class="-m-1 grid max-h-menu list-none gap-0.5 overflow-y-auto p-1"
			>
				{#each organizations as organization (organization.id)}
					{@const selected = organization.id === current?.id}
					{@const name = secondaryName(organization)}
					<li>
						<a
							href={href(organization)}
							aria-current={selected ? 'true' : undefined}
							onclick={menu.close}
							class="flex min-w-0 items-center gap-2 rounded-md px-2.5 py-2 text-app-fg no-underline hover:bg-app-sidebar-hover"
						>
							<span class="min-w-0 flex-1">
								<span class="block text-sm font-medium wrap-anywhere"
									>{displayName(organization)}</span
								>
								{#if name}
									<span class="mono block text-xs text-app-muted wrap-anywhere">{name}</span>
								{/if}
							</span>
							{#if selected}
								<Check size={16} class="shrink-0 text-brand-strong" aria-hidden="true" />
							{/if}
						</a>
					</li>
				{/each}
			</ul>
			<a
				href={resolve('/orgs')}
				onclick={menu.close}
				class="mt-1 flex items-center border-t border-app-line px-2.5 py-2.5 text-sm font-semibold text-brand-strong no-underline hover:bg-app-sidebar-hover"
				>All organizations</a
			>
		</div>
	</details>
{/if}
