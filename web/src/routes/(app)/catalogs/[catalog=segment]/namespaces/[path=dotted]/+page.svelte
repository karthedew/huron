<script lang="ts">
	import { page } from '$app/state';
	import Badge from '$design/components/Badge.svelte';
	import CliHint from '$design/components/CliHint.svelte';
	import CollectionList from '$design/components/CollectionList.svelte';
	import CopyText from '$design/components/CopyText.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import NamespaceHint from '$design/components/NamespaceHint.svelte';
	import NamespaceList from '$design/components/NamespaceList.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { cliCommand } from '$lib/cli';
	import { displayName } from '$lib/names';
	import { namespaceContents, namespaceKind } from '$lib/namespaces';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const namespace = $derived(data.namespace);
	const catalog = $derived(data.catalog);
	const kind = $derived(namespaceKind(namespace));
	const can = $derived(catalogCapabilities(data.roles, catalog, data.organizations));
	/** Whether a list shows a later page; its empty first page says what the namespace lacks. */
	const namespacesPaged = $derived(Boolean(page.url.searchParams.get('namespaces_cursor')));
	const collectionsPaged = $derived(Boolean(page.url.searchParams.get('collections_cursor')));
	const showNamespaces = $derived(
		data.namespaces.length > 0 || namespacesPaged || !namespace.collections_allowed
	);
	const showCollections = $derived(
		data.collections.length > 0 || collectionsPaged || namespace.collections_allowed
	);
	const createCollection = $derived(
		cliCommand({
			verb: 'collection create',
			catalog: catalog.name,
			namespace: namespace.identifier
		})
	);
</script>

<svelte:head><title>{pageTitle(namespace.path, displayName(catalog))}</title></svelte:head>

{#snippet collectionHint()}
	<CliHint title="Create a collection here" command={createCollection} />
{/snippet}

{#snippet namespaceHint()}
	<NamespaceHint catalog={catalog.name} parent={namespace.identifier} />
{/snippet}

<PageExpiredNotice />
<header class="border-b border-app-line pb-5">
	<p class="m-0 text-xs font-semibold tracking-wide text-app-muted uppercase">Namespace</p>
	<h1 class="mt-1 wrap-anywhere">{namespace.name}</h1>
	<p class="mono mt-1 mb-0 text-sm break-all text-app-muted">{namespace.identifier}</p>
	<p class="mt-3 mb-0 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
		<Badge tone={kind.tone}>{kind.label}</Badge>
		<span class="text-app-muted">{namespaceContents(namespace)}</span>
	</p>
	<dl class="mt-3 mb-0 grid gap-1 text-sm">
		<dt class="text-xs font-semibold text-app-muted">Share path</dt>
		<dd class="m-0 min-w-0"><CopyText label="share path" value={data.sharePath} /></dd>
	</dl>
</header>

{#if showNamespaces}
	<section aria-labelledby="namespace-namespaces" class="mt-6">
		<h2 id="namespace-namespaces" class="m-0 mb-3 border-0 p-0 text-base font-semibold">
			Namespaces
		</h2>
		{#if data.namespaces.length > 0}
			<NamespaceList label="Namespaces in {namespace.name}" namespaces={data.namespaces} />
		{:else if namespacesPaged}
			<p class="m-0 text-app-muted">No namespaces on this page.</p>
		{:else}
			<EmptyState title="No namespaces yet.">
				{#if can.administerCatalog}
					<div class="mx-auto mt-4 max-w-2xl">{@render namespaceHint()}</div>
				{/if}
			</EmptyState>
		{/if}
		<Pager label="Namespace pages" next={data.namespacesNext} param="namespaces_cursor" />
		{#if can.administerCatalog && !namespace.collections_allowed && data.namespaces.length > 0}
			<div class="mt-6 max-w-3xl">{@render namespaceHint()}</div>
		{/if}
	</section>
{/if}

{#if showCollections}
	<section aria-labelledby="namespace-collections" class="mt-8">
		<h2 id="namespace-collections" class="m-0 mb-3 border-0 p-0 text-base font-semibold">
			Collections
		</h2>
		{#if data.collections.length > 0}
			<CollectionList label="Collections in {namespace.name}" collections={data.collections} />
		{:else if collectionsPaged}
			<p class="m-0 text-app-muted">No collections on this page.</p>
		{:else}
			<EmptyState title="No collections yet.">
				{#if can.contribute && namespace.collections_allowed}
					<div class="mx-auto mt-4 max-w-2xl">{@render collectionHint()}</div>
				{/if}
			</EmptyState>
		{/if}
		<Pager label="Collection pages" next={data.collectionsNext} param="collections_cursor" />
		{#if can.contribute && namespace.collections_allowed && data.collections.length > 0}
			<div class="mt-6 max-w-3xl">{@render collectionHint()}</div>
		{/if}
	</section>
{/if}
