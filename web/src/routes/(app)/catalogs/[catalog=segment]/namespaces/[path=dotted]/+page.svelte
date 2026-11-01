<script lang="ts">
	import { page } from '$app/state';
	import Badge from '$design/components/Badge.svelte';
	import CollectionList from '$design/components/CollectionList.svelte';
	import CopyText from '$design/components/CopyText.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import NamespaceList from '$design/components/NamespaceList.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { displayName } from '$lib/names';
	import { namespaceContents, namespaceKind } from '$lib/namespaces';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	const namespace = $derived(data.namespace);
	const kind = $derived(namespaceKind(namespace));
	const namespacesPaged = $derived(Boolean(page.url.searchParams.get('namespaces_cursor')));
	const collectionsPaged = $derived(Boolean(page.url.searchParams.get('collections_cursor')));
	const showNamespaces = $derived(
		data.namespaces.length > 0 || namespacesPaged || !namespace.collections_allowed
	);
	const showCollections = $derived(
		data.collections.length > 0 || collectionsPaged || namespace.collections_allowed
	);
</script>

<svelte:head><title>{pageTitle(namespace.path, displayName(data.catalog))}</title></svelte:head>
<PageExpiredNotice />
<div class="mb-6">
	<p class="mt-0 mb-3 flex flex-wrap items-center gap-3 text-sm">
		<Badge tone={kind.tone}>{kind.label}</Badge><span class="text-app-muted"
			>{namespaceContents(namespace)}</span
		>
	</p>
	<dl class="m-0 text-sm">
		<dt class="text-xs text-app-muted">Share path</dt>
		<dd class="m-0 min-w-0"><CopyText label="share path" value={data.sharePath} /></dd>
	</dl>
</div>
{#if showNamespaces}
	<section aria-labelledby="namespace-namespaces">
		<h2 id="namespace-namespaces" class="m-0 mb-3 border-0 p-0 text-base font-semibold">
			Namespaces
		</h2>
		{#if data.namespaces.length > 0}<NamespaceList
				label="Namespaces in {namespace.name}"
				namespaces={data.namespaces}
				sort={data.namespaceSort}
				prefix="namespaces"
			/>
		{:else if namespacesPaged}<p class="m-0 text-app-muted">No namespaces on this page.</p>
		{:else}<EmptyState title="No namespaces yet." />{/if}
		<Pager label="Namespace pages" next={data.namespacesNext} param="namespaces_cursor" />
	</section>
{/if}
{#if showCollections}
	<section aria-labelledby="namespace-collections" class="mt-8">
		<h2 id="namespace-collections" class="m-0 mb-3 border-0 p-0 text-base font-semibold">
			Collections
		</h2>
		{#if data.collections.length > 0}<CollectionList
				label="Collections in {namespace.name}"
				collections={data.collections}
				sort={data.collectionSort}
				prefix="collections"
			/>
		{:else if collectionsPaged}<p class="m-0 text-app-muted">No collections on this page.</p>
		{:else}<EmptyState title="No collections yet." />{/if}
		<Pager label="Collection pages" next={data.collectionsNext} param="collections_cursor" />
	</section>
{/if}
