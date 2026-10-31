<script lang="ts">
	import { page } from '$app/state';
	import EmptyState from '$design/components/EmptyState.svelte';
	import NamespaceHint from '$design/components/NamespaceHint.svelte';
	import NamespaceList from '$design/components/NamespaceList.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { displayName } from '$lib/names';
	import { visibleOrganization } from '$lib/organizations';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const catalog = $derived(data.catalog);
	const owner = $derived(visibleOrganization(catalog.organization, data.organizations));
	const can = $derived(catalogCapabilities(data.roles, catalog, data.organizations));
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
	const title = $derived(
		pageTitle(displayName(catalog), owner ? displayName(owner) : catalog.organization)
	);
</script>

<svelte:head><title>{title}</title></svelte:head>

<PageExpiredNotice />
<section aria-labelledby="catalog-namespaces">
	<h2 id="catalog-namespaces" class="m-0 mb-3 border-0 p-0 text-base font-semibold">Namespaces</h2>
	{#if data.namespaces.length > 0}
		<NamespaceList label="Top-level namespaces" namespaces={data.namespaces} />
		<Pager label="Namespace pages" next={data.nextCursor} />
		{#if can.administerCatalog}
			<div class="mt-6 max-w-3xl">
				<NamespaceHint catalog={catalog.name} parent={catalog.name} />
			</div>
		{/if}
	{:else if firstPage}
		<EmptyState title="No namespaces yet.">
			{#if can.administerCatalog}
				<div class="mx-auto mt-4 max-w-2xl">
					<NamespaceHint catalog={catalog.name} parent={catalog.name} />
				</div>
			{/if}
		</EmptyState>
	{:else}
		<p class="m-0 text-app-muted">No namespaces on this page.</p>
		<Pager label="Namespace pages" next={data.nextCursor} />
	{/if}
</section>
