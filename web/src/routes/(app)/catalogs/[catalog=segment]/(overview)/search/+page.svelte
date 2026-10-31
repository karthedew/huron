<script lang="ts">
	import { ArrowRight } from '@lucide/svelte';
	import CliHint from '$design/components/CliHint.svelte';
	import NoSearchResults from '$design/components/NoSearchResults.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import SearchForm from '$design/components/SearchForm.svelte';
	import SearchResults from '$design/components/SearchResults.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { cliCommand } from '$lib/cli';
	import { displayName } from '$lib/names';
	import { visibleOrganization } from '$lib/organizations';
	import { atPage, emptySearch, hasErrors, labelText, type Search } from '$lib/search';
	import { catalogSearchHref, organizationSearchHref } from '$lib/search-links';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const catalog = $derived(data.catalog);
	const search = $derived(data.search);
	const owner = $derived(visibleOrganization(catalog.organization, data.organizations));
	const can = $derived(catalogCapabilities(data.roles, catalog, data.organizations));
	const title = $derived.by(() => {
		const context = displayName(catalog);
		if (hasErrors(data.errors)) return pageTitle('Error: Search', context);
		if (search.q === '') return pageTitle('Search', context);
		return pageTitle(`“${search.q}”`, 'Search', context);
	});
	/**
	 * The organization's search for the same text and labels, linked under the results and among
	 * the ways out when nothing matches. Its catalogs differ in who may see drafts, so the states
	 * stay here.
	 */
	const wider = $derived.by(() => {
		const same: Search = { ...emptySearch(), q: search.q, labels: search.labels };
		return {
			label: `Search all of ${owner ? displayName(owner) : catalog.organization}`,
			href: organizationSearchHref(catalog.organization, same)
		};
	});
	const command = $derived(
		cliCommand({
			verb: 'search',
			catalog: catalog.name,
			q: search.q,
			labels: search.labels.map(labelText),
			states: search.states ?? []
		})
	);

	function href(other: Search): string {
		return catalogSearchHref(catalog.name, other);
	}

	function pageHref(cursor: string | null): string {
		return href(atPage(search, cursor));
	}
</script>

<svelte:head><title>{title}</title></svelte:head>

<SearchForm
	label="Catalog search"
	action={href(emptySearch())}
	{search}
	errors={data.errors}
	pendingLabel={data.pendingLabel}
	drafts={can.contribute}
	{href}
/>
<PageExpiredNotice />
{#if data.exact !== null}
	<section aria-labelledby="search-exact" class="mt-6">
		<h2 id="search-exact" class="m-0 mb-3 border-0 p-0 text-base font-semibold">Exact match</h2>
		<SearchResults label="Exact match" results={[data.exact]} {search} {href} />
	</section>
{/if}
{#if data.results !== null}
	<section aria-labelledby="search-results" class="mt-6">
		<h2 id="search-results" class="m-0 mb-3 border-0 p-0 text-base font-semibold">Results</h2>
		{#if data.results.length === 0 && data.exact === null && search.cursor === null}
			<!-- Nothing found: the wider search is one of the ways out it offers. -->
			<NoSearchResults {search} {href} {wider} />
		{:else}
			{#if data.results.length > 0}
				<SearchResults label="Results" results={data.results} {search} {href} />
			{:else if data.exact !== null}
				<p class="m-0 text-app-muted">No other collections match this search.</p>
			{:else}
				<p class="m-0 text-app-muted">No results on this page.</p>
			{/if}
			<p class="mt-2 mb-0 text-sm">
				<a
					href={wider.href}
					class="inline-flex max-w-full items-center gap-1 font-semibold wrap-anywhere"
					>{wider.label}<ArrowRight size={14} class="shrink-0" aria-hidden="true" /></a
				>
			</p>
		{/if}
		<Pager label="Result pages" next={data.nextCursor} href={pageHref} />
	</section>
	<div class="mt-6 max-w-3xl">
		<CliHint title="Run this search with the CLI" {command} />
	</div>
{/if}
