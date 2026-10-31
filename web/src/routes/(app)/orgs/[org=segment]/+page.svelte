<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Database } from '@lucide/svelte';
	import CliHint from '$design/components/CliHint.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import { capabilities } from '$lib/capabilities';
	import { cliCommand } from '$lib/cli';
	import { countLabel } from '$lib/format';
	import { displayName, secondaryName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const organization = $derived(data.organizationDetails);
	const can = $derived(capabilities(data.roles, { organizationId: organization.id }));
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
</script>

<svelte:head><title>{pageTitle('Catalogs', displayName(organization))}</title></svelte:head>

<PageExpiredNotice />
{#if data.catalogs.length > 0}
	<ul class="m-0 grid list-none gap-3 p-0" aria-label="Catalogs">
		{#each data.catalogs as catalog (catalog.id)}
			{@const name = secondaryName(catalog)}
			<li
				class="@container rounded-card border border-app-line bg-app-card px-4 py-3.5 hover:border-app-line-strong"
			>
				<div class="flex flex-col gap-3 @2xl:flex-row @2xl:items-start @2xl:justify-between">
					<div class="flex min-w-0 gap-3">
						<Database size={18} class="mt-0.5 shrink-0 text-brand-strong" aria-hidden="true" />
						<div class="min-w-0">
							<a
								href={resolve('/(app)/catalogs/[catalog=segment]', { catalog: catalog.name })}
								class="font-semibold wrap-anywhere text-app-fg no-underline hover:underline"
								>{displayName(catalog)}</a
							>
							{#if name}
								<p class="mono m-0 text-xs wrap-anywhere text-app-muted">{name}</p>
							{/if}
							{#if catalog.description}
								<p class="mt-1.5 mb-0 text-sm wrap-anywhere text-app-muted">
									{catalog.description}
								</p>
							{/if}
						</div>
					</div>
					<p
						class="m-0 flex shrink-0 flex-wrap gap-x-4 gap-y-1 pl-7.5 text-xs text-app-muted @2xl:pl-0 @2xl:text-right"
					>
						<span
							>Schema <a
								href={resolve('/(app)/catalogs/[catalog=segment]/(overview)/schema', {
									catalog: catalog.name
								})}
								class="mono font-semibold wrap-anywhere"
								>{catalog.schema.name} v{catalog.schema.version}</a
							></span
						>
						<span>{countLabel(catalog.namespace_count, 'namespace')} in total</span>
					</p>
				</div>
			</li>
		{/each}
	</ul>
{:else if firstPage}
	<EmptyState title="No catalogs you can see in this organization.">
		{#if can.administerOrganization}
			<div class="mx-auto mt-4 max-w-2xl">
				<CliHint
					title="Create a catalog in this organization"
					command={cliCommand({ verb: 'catalog create', organization: organization.name })}
				/>
			</div>
		{/if}
	</EmptyState>
{:else}
	<p class="text-app-muted">No catalogs on this page.</p>
{/if}
<Pager label="Catalog pages" next={data.nextCursor} />
