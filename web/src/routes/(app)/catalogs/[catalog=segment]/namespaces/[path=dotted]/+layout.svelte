<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import CopyIdentifier from '$design/components/CopyIdentifier.svelte';
	import SectionNav from '$design/components/SectionNav.svelte';
	import type { LayoutProps } from './$types';
	let { data, children }: LayoutProps = $props();
	const namespace = $derived(data.namespace);
	const params = $derived({ catalog: data.catalog.name, path: namespace.path });
	const sections = $derived([
		{
			label: 'Overview',
			href: resolve('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]', params),
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]'
		},
		{
			label: 'CLI',
			href: resolve('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]/cli', params),
			current: page.route.id === '/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]/cli'
		}
	]);
</script>

<header class="border-b border-app-line">
	<div class="relative flex min-w-0 items-start gap-2">
		<h1 class="m-0 min-w-0 text-xl leading-8 font-semibold wrap-anywhere">{namespace.name}</h1>
		<CopyIdentifier value={namespace.identifier} />
	</div>
	<SectionNav label="Namespace" {sections} />
</header>
<div class="mt-6">{@render children()}</div>
