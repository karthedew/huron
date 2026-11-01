<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import CopyIdentifier from '$design/components/CopyIdentifier.svelte';
	import SectionNav from '$design/components/SectionNav.svelte';
	import { displayName } from '$lib/names';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const organization = $derived(data.organizationDetails);
	const sections = $derived([
		{
			label: 'Catalogs',
			href: resolve('/(app)/orgs/[org=segment]', { org: organization.name }),
			current: page.route.id === '/(app)/orgs/[org=segment]',
			count: organization.catalog_count
		},
		{
			label: 'Access',
			href: resolve('/(app)/orgs/[org=segment]/access', { org: organization.name }),
			current: page.route.id === '/(app)/orgs/[org=segment]/access'
		},
		{
			label: 'CLI',
			href: resolve('/(app)/orgs/[org=segment]/cli', { org: organization.name }),
			current: page.route.id === '/(app)/orgs/[org=segment]/cli'
		}
	]);
</script>

<header class="border-b border-app-line">
	<div class="relative flex min-w-0 items-start gap-2">
		<h1 class="m-0 min-w-0 text-xl leading-8 font-semibold wrap-anywhere">
			{displayName(organization)}
		</h1>
		<CopyIdentifier value={organization.name} />
	</div>
	<SectionNav label="Organization" {sections} />
</header>

<div class="mt-6">{@render children()}</div>
