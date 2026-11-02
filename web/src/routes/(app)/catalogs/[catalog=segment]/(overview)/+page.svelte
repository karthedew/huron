<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import EmptyState from '$design/components/EmptyState.svelte';
	import NamespaceList from '$design/components/NamespaceList.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { countLabel } from '$lib/format';
	import { displayName } from '$lib/names';
	import { visibleOrganization } from '$lib/organizations';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	const catalog = $derived(data.catalog);
	const owner = $derived(visibleOrganization(catalog.organization, data.organizations));
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
	const title = $derived(
		pageTitle(displayName(catalog), owner ? displayName(owner) : catalog.organization)
	);
</script>

<svelte:head><title>{title}</title></svelte:head>
<PageExpiredNotice />
{#if catalog.description}<p class="mt-0 mb-4 max-w-3xl wrap-anywhere">{catalog.description}</p>{/if}
<dl class="mt-0 mb-6 flex flex-wrap gap-x-6 gap-y-3 text-sm">
	<div>
		<dt class="text-xs text-app-muted">Organization</dt>
		<dd class="m-0">
			<a href={resolve('/(app)/orgs/[org=segment]', { org: catalog.organization })}
				>{owner ? displayName(owner) : catalog.organization}</a
			>
		</dd>
	</div>
	<div>
		<dt class="text-xs text-app-muted">Schema</dt>
		<dd class="m-0">
			<a
				href={resolve('/(app)/catalogs/[catalog=segment]/(overview)/schema', {
					catalog: catalog.name
				})}>{catalog.schema.name} v{catalog.schema.version}</a
			>
		</dd>
	</div>
	<div>
		<dt class="text-xs text-app-muted">Contents</dt>
		<dd class="m-0">{countLabel(catalog.namespace_count, 'namespace')} in total</dd>
	</div>
</dl>
<section aria-labelledby="catalog-namespaces">
	<h2 id="catalog-namespaces" class="m-0 mb-3 border-0 p-0 text-base font-semibold">Namespaces</h2>
	{#if data.namespaces.length > 0}
		<NamespaceList
			label="Top-level namespaces"
			namespaces={data.namespaces}
			sort={data.namespaceSort}
		/>
	{:else if firstPage}
		<EmptyState title="No namespaces yet." />
	{:else}<p class="m-0 text-app-muted">No namespaces on this page.</p>{/if}
	<Pager label="Namespace pages" next={data.nextCursor} />
</section>
