<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import Breadcrumbs from '$design/components/Breadcrumbs.svelte';
	import Explorer from '$design/components/Explorer.svelte';
	import { currentNamespace, explorerCurrent, lastSegment, pathPrefixes } from '$lib/explorer';
	import { displayName } from '$lib/names';
	import { visibleOrganization } from '$lib/organizations';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	/**
	 * Where the page is in the tree. An error page (`+error.svelte`) stands in the catalog alone:
	 * the namespace or collection its address names may not exist.
	 */
	const current = $derived(explorerCurrent(page.error ? null : page.route.id, page.params));
	/** The root from this layout and, on namespace and collection pages, the page's trail. */
	const levels = $derived([data.root, ...(page.data.trail ?? [])]);
	const owner = $derived(visibleOrganization(data.organization, data.organizations));

	const crumbs = $derived.by(() => {
		const catalog = data.catalog.name;
		const namespace = currentNamespace(current);
		return [
			{
				label: owner ? displayName(owner) : data.organization,
				href: resolve('/(app)/orgs/[org=segment]', { org: data.organization })
			},
			{
				label: displayName(data.catalog),
				href: resolve('/(app)/catalogs/[catalog=segment]', { catalog }),
				current: current.kind === 'catalog' && current.overview
			},
			...(namespace === null ? [] : pathPrefixes(namespace)).map((path) => ({
				label: lastSegment(path),
				href: resolve('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]', {
					catalog,
					path
				}),
				current: current.kind === 'namespace' && current.path === path
			})),
			...(current.kind === 'collection'
				? [
						{
							label: current.name,
							href: resolve('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]', {
								catalog,
								identifier: `${current.namespace}.${current.name}`
							}),
							// On the collection's other tabs, its sub-navigation marks the page.
							current: current.overview
						}
					]
				: [])
		];
	});
</script>

<!--
	The explorer follows the content, so the skip link and the keyboard reach the page first;
	from lg it is drawn in its own column on the left, where it stays in view as the page scrolls.
-->
<div class="grid gap-x-8 gap-y-6 lg:grid-cols-explorer">
	<div class="min-w-0 lg:col-start-2 lg:row-start-1">
		<div class="mb-5"><Breadcrumbs {crumbs} /></div>
		{@render children()}
	</div>
	<div class="hidden min-w-0 lg:col-start-1 lg:row-start-1 lg:block">
		{#key data.catalog.name}
			<Explorer
				organization={data.organization}
				catalogs={data.catalogs}
				moreCatalogs={data.moreCatalogs}
				catalog={data.catalog}
				{levels}
				{current}
			/>
		{/key}
	</div>
</div>
