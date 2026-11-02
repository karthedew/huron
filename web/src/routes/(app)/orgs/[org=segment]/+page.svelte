<script lang="ts">
	import { page } from '$app/state';
	import CatalogList from '$design/components/CatalogList.svelte';
	import CopyText from '$design/components/CopyText.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	const organization = $derived(data.organizationDetails);
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
</script>

<svelte:head><title>{pageTitle('Catalogs', displayName(organization))}</title></svelte:head>
<PageExpiredNotice />
{#if organization.description}<p class="mt-0 mb-4 max-w-3xl wrap-anywhere">
		{organization.description}
	</p>{/if}
<dl class="mt-0 mb-6 text-sm">
	<dt class="text-xs text-app-muted">Share path</dt>
	<dd class="m-0 min-w-0"><CopyText label="share path" value={data.organizationPath} /></dd>
	{#if organization.declared}<dd class="m-0 mt-1 text-xs text-app-muted">
			Declared in the service configuration.
		</dd>{/if}
</dl>
{#if data.catalogs.length > 0}<CatalogList catalogs={data.catalogs} sort={data.catalogSort} />
{:else if firstPage}<EmptyState title="No catalogs you can see in this organization." />
{:else}<p class="text-app-muted">No catalogs on this page.</p>{/if}
<Pager label="Catalog pages" next={data.nextCursor} />
