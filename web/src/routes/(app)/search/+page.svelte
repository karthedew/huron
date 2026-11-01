<script lang="ts">
	import { resolve } from '$app/paths';
	import CatalogSearch from '$design/components/CatalogSearch.svelte';
	import OrganizationSearch from '$design/components/OrganizationSearch.svelte';
	import NoOrganizations from '$design/components/NoOrganizations.svelte';
	import { displayName } from '$lib/names';
	import { formLabel } from '$lib/search';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>{pageTitle('Search')}</title></svelte:head>

<div class="min-w-0">
	<header class="mb-6">
		<h1 class="m-0 text-2xl font-semibold tracking-tight">Search</h1>
		<p class="mt-2 mb-0 text-sm text-app-muted">
			Find collections by text, metadata labels and state.
		</p>
	</header>
	{#if data.selectedOrganization === null}
		<NoOrganizations groups={data.user.groups} />
	{:else}
		<form
			method="GET"
			action={resolve('/(app)/search')}
			aria-label="Search organization"
			class="mb-5 flex flex-col items-stretch gap-3 sm:flex-row sm:items-end"
		>
			{#if data.search.q}<input type="hidden" name="q" value={data.search.q} />{/if}
			{#each data.search.states ?? [] as state (state)}
				<input type="hidden" name="state" value={state} />
			{/each}
			{#each data.search.labels as filter (filter.key + '=' + filter.value)}
				{@const kept = formLabel(filter)}
				<input type="hidden" name={kept.name} value={kept.value} />
			{/each}
			<div class="min-w-0 flex-1 sm:max-w-lg">
				<label for="search-organization" class="mb-1.5 block text-sm font-semibold"
					>Organization</label
				>
				<select
					id="search-organization"
					name="organization"
					value={data.organization ?? ''}
					class="w-full min-w-0 rounded-md border border-app-line-strong bg-app-bg px-3 py-2 text-sm"
				>
					{#each data.organizationList as organization (organization.id)}
						<option value={organization.name}>{displayName(organization)}</option>
					{/each}
				</select>
			</div>
			<button
				type="submit"
				class="self-start rounded-md border border-app-line-strong bg-app-card px-3 py-2 text-sm font-semibold hover:bg-app-hover sm:self-auto"
				>Choose organization</button
			>
		</form>
		{#if data.moreOrganizations}
			<p class="mb-4 text-sm text-app-muted">
				The selector shows the first 500 organizations you can see, plus the selected organization. <a
					href={resolve('/orgs')}>Browse all organizations</a
				> to choose another.
			</p>
		{/if}
		{#if data.catalogSearch !== null}
			<CatalogSearch
				data={{ ...data.catalogSearch, roles: data.roles, organizations: data.organizations }}
			/>
		{:else if data.organizationSearch !== null}
			<OrganizationSearch data={data.organizationSearch} />
		{/if}
		<p class="mt-5 text-xs text-app-muted">
			Text searches identifiers, titles and descriptions. Labels match exact metadata values. Schema
			fields and other metadata properties are not searchable yet.
		</p>
	{/if}
</div>
