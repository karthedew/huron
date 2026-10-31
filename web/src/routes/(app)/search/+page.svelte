<script lang="ts">
	import { CircleAlert } from '@lucide/svelte';
	import NoOrganizations from '$design/components/NoOrganizations.svelte';
	import { formatList } from '$lib/format';
	import { displayName } from '$lib/names';
	import { hasErrors, sharedSearch } from '$lib/search';
	import { organizationSearchHref } from '$lib/search-links';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	/** What each organization's link searches: one per organization, each with a bounded query. */
	const shared = $derived(sharedSearch(data.search, data.organizationList.length));
	/** What the links leave out of the address's search, being too long to repeat for each. */
	const dropped = $derived(
		shared.q !== data.search.q
			? 'all of it'
			: shared.labels.length < data.search.labels.length
				? 'its label filters'
				: null
	);
	const search = $derived(data.search);
	const title = $derived.by(() => {
		if (hasErrors(data.errors)) return pageTitle('Error: Search');
		if (search.q === '') return pageTitle('Search');
		return pageTitle(`“${search.q}”`, 'Search');
	});
	/** Why each part of the address that is left out of the search is: the text, the labels. */
	const refusals = $derived(
		(['q', 'label'] as const).flatMap((field) => {
			const message = data.errors[field];
			return message === null ? [] : [{ field, message }];
		})
	);
	/** What the links search for, in words: its text, then its label filters. */
	const lead = $derived.by(() => {
		const labels = shared.labels.map(({ key, value }) => `${key} = ${value}`);
		const parts = [
			...(shared.q === '' ? [] : [`“${shared.q}”`]),
			...(labels.length === 0 ? [] : [`with ${formatList(labels)}`])
		];
		return parts.length === 0
			? 'Choose the organization to search:'
			: `Search ${parts.join(' ')} in:`;
	});
</script>

<svelte:head><title>{title}</title></svelte:head>

<h1>Search</h1>
{#if data.organizationList.length === 0}
	<div class="mt-6"><NoOrganizations groups={data.user.groups} /></div>
{:else}
	{#if refusals.length > 0}
		<div class="mt-3 grid gap-1.5">
			{#each refusals as refusal (refusal.field)}
				<p class="m-0 flex items-start gap-1.5 text-sm font-semibold text-app-danger">
					<CircleAlert size={16} class="mt-0.5 shrink-0" aria-hidden="true" />{refusal.message}
				</p>
			{/each}
		</div>
	{/if}
	{#if dropped !== null}
		<p class="mt-3 mb-0 text-sm text-app-muted">
			This search is too long to repeat in a link to each organization, so the links leave out
			{dropped}.
		</p>
	{/if}
	<p class="mt-4 mb-0 wrap-anywhere">{lead}</p>
	<ul class="m-0 mt-3 flex list-none flex-wrap gap-2 p-0" aria-label="Organizations">
		{#each data.organizationList as organization (organization.id)}
			<li class="max-w-full">
				<a
					href={organizationSearchHref(organization.name, shared)}
					class="inline-flex min-h-9 max-w-full items-center rounded-md border border-app-line-strong bg-app-card px-3 py-1.5 text-sm font-semibold wrap-anywhere text-app-fg no-underline hover:border-brand-strong hover:underline"
					>{displayName(organization)}</a
				>
			</li>
		{/each}
	</ul>
{/if}
