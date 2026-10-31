<script lang="ts">
	import { resolve } from '$app/paths';
	import { ArrowRight, CircleAlert, Database } from '@lucide/svelte';
	import Callout from '$design/components/Callout.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import NoSearchResults from '$design/components/NoSearchResults.svelte';
	import SearchForm from '$design/components/SearchForm.svelte';
	import SearchResults from '$design/components/SearchResults.svelte';
	import { countLabel, formatCount, formatList } from '$lib/format';
	import { displayName } from '$lib/names';
	import {
		CATALOG_RESULTS,
		ORGANIZATION_CATALOGS,
		emptySearch,
		hasErrors,
		type Search
	} from '$lib/search';
	import { catalogSearchHref, organizationSearchHref } from '$lib/search-links';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const organization = $derived(data.organizationDetails);
	const search = $derived(data.search);
	const results = $derived(data.results);
	const title = $derived.by(() => {
		const context = displayName(organization);
		if (hasErrors(data.errors)) return pageTitle('Error: Search', context);
		if (search.q === '') return pageTitle('Search', context);
		return pageTitle(`“${search.q}”`, 'Search', context);
	});
	const answers = $derived(results?.answers ?? []);
	/** The catalogs shown under their own headings: those with results, and those that failed. */
	const shown = $derived(
		answers.filter((answer) => answer.status === 'failed' || answer.results.length > 0)
	);
	/** The catalogs that answered with nothing to show. */
	const quiet = $derived(
		answers.filter((answer) => answer.status === 'answered' && answer.results.length === 0)
	);
	const answered = $derived(answers.filter((answer) => answer.status === 'answered').length);
	const found = $derived(
		results !== null &&
			(results.exact !== null ||
				answers.some((answer) => answer.status === 'answered' && answer.results.length > 0))
	);
	/** Whether some catalogs said nothing: they failed, or did not answer in time. */
	const partial = $derived(answered < answers.length || (results?.late.length ?? 0) > 0);

	function href(other: Search): string {
		return organizationSearchHref(organization.name, other);
	}
</script>

<svelte:head><title>{title}</title></svelte:head>

<SearchForm
	label="Organization search"
	action={href(emptySearch())}
	{search}
	errors={data.errors}
	pendingLabel={data.pendingLabel}
	drafts={data.drafts}
	{href}
/>
{#if data.truncated}
	<Callout>
		This organization has more than {formatCount(ORGANIZATION_CATALOGS)} catalogs; its search covers the
		first {formatCount(ORGANIZATION_CATALOGS)}, by name.
	</Callout>
{/if}
{#if data.catalogCount === 0}
	<div class="mt-6"><EmptyState title="No catalogs you can see in this organization." /></div>
{:else if results === null}
	{#if !hasErrors(data.errors)}
		<p class="mt-4 mb-0 text-sm text-app-muted">
			Searches {data.catalogCount === 1
				? 'the catalog'
				: `the ${formatCount(data.catalogCount)} catalogs`} of {displayName(organization)} that you can
			see, and shows the first {formatCount(CATALOG_RESULTS)} results of each.
		</p>
	{/if}
{:else}
	{#if results.late.length > 0}
		<Callout kind="warn">
			<p class="m-0 font-semibold">
				{countLabel(results.late.length, 'catalog')} did not answer in time.
			</p>
			<ul
				class="m-0 mt-1.5 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-sm"
				aria-label="Catalogs that did not answer in time"
			>
				{#each results.late as late (late.name)}
					<li class="max-w-full wrap-anywhere">
						<a
							href={catalogSearchHref(late.name, late.search)}
							class="font-semibold underline underline-offset-2">Search only {late.displayName}</a
						>
					</li>
				{/each}
			</ul>
		</Callout>
	{/if}
	{#if results.skipped.length > 0}
		<Callout>
			Not searched, because only those who may create collections there see drafts: {formatList(
				results.skipped.map((skipped) => skipped.displayName)
			)}.
		</Callout>
	{/if}
	{#if results.exact !== null}
		<section aria-labelledby="search-exact" class="mt-6">
			<h2 id="search-exact" class="m-0 mb-3 border-0 p-0 text-base font-semibold">Exact match</h2>
			<SearchResults label="Exact match" results={[results.exact]} {search} />
		</section>
	{/if}
	{#each shown as answer (answer.name)}
		<section aria-labelledby="results-{answer.name}" class="mt-6">
			<h2
				id="results-{answer.name}"
				class="m-0 mb-3 flex items-center gap-2 border-0 p-0 text-base font-semibold"
			>
				<Database size={16} class="shrink-0 text-brand-strong" aria-hidden="true" />
				<a
					href={resolve('/(app)/catalogs/[catalog=segment]', { catalog: answer.name })}
					class="min-w-0 wrap-anywhere text-app-fg no-underline hover:underline"
					>{answer.displayName}</a
				>
			</h2>
			{#if answer.status === 'failed'}
				<p
					class="m-0 flex items-start gap-2 rounded-card border border-app-warn-line bg-app-warn px-4 py-3 text-sm"
				>
					<CircleAlert size={16} class="mt-0.5 shrink-0" aria-hidden="true" />Couldn't search this
					catalog.
				</p>
			{:else}
				<SearchResults label="Results in {answer.displayName}" results={answer.results} {search} />
			{/if}
			<p class="mt-2 mb-0 text-sm">
				<a
					href={catalogSearchHref(answer.name, answer.search)}
					class="inline-flex max-w-full items-center gap-1 font-semibold wrap-anywhere"
					>{answer.status === 'answered' && answer.more
						? `See all results in ${answer.displayName}`
						: `Search only ${answer.displayName}`}<ArrowRight
						size={14}
						class="shrink-0"
						aria-hidden="true"
					/></a
				>
			</p>
		</section>
	{/each}
	{#if !found}
		<!-- Where some catalogs said nothing, the notes above say which; with none answering, they say all. -->
		{#if answered > 0 || !partial}
			<div class="mt-6">
				<NoSearchResults
					{search}
					{href}
					wider={null}
					title={partial ? 'No collections match in the catalogs that answered.' : undefined}
				/>
			</div>
		{/if}
	{:else if quiet.length > 0}
		<p class="mt-6 mb-0 text-sm wrap-anywhere text-app-muted">
			No {results.exact === null ? '' : 'other '}collections match in {formatList(
				quiet.map((answer) => answer.displayName)
			)}.
		</p>
	{/if}
{/if}
