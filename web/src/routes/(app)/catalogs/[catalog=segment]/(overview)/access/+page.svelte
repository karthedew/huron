<script lang="ts">
	import { Lock } from '@lucide/svelte';
	import { ROLES, type Role } from '$api/types';
	import Badge from '$design/components/Badge.svelte';
	import CliHint from '$design/components/CliHint.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { cliCommand } from '$lib/cli';
	import { displayName } from '$lib/names';
	import { visibleOrganization } from '$lib/organizations';
	import { ROLE_ABILITIES, ROLE_NAMES } from '$lib/roles';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const catalog = $derived(data.catalog);
	const owner = $derived(visibleOrganization(catalog.organization, data.organizations));
	const can = $derived(catalogCapabilities(data.roles, catalog, data.organizations));
	const mine = $derived(new Set(data.user.groups));
	const grantCommand = $derived(
		[
			cliCommand({ verb: 'catalog grant', catalog: catalog.name }),
			cliCommand({ verb: 'acl apply', catalog: catalog.name })
		].join('\n')
	);

	/** Where a role comes from when it is not granted on the catalog itself. */
	function inheritedFrom(role: Role): string | null {
		if (role === 'platform_admin') return 'Inherited from the platform';
		if (role === 'org_admin') {
			return `Inherited from ${owner ? displayName(owner) : catalog.organization}`;
		}
		return null;
	}
</script>

<svelte:head><title>{pageTitle('Access', displayName(catalog))}</title></svelte:head>

<section aria-labelledby="catalog-access">
	<h2 id="catalog-access" class="m-0 border-0 p-0 text-base font-semibold">Who has access</h2>
	{#if data.groups === null}
		<p class="mt-3 mb-0 flex items-center gap-2">
			<Lock size={16} class="shrink-0 text-app-muted" aria-hidden="true" />You don't have permission
			to see this.
		</p>
	{:else}
		{@const groups = data.groups}
		<p class="mt-2 mb-4 max-w-3xl text-sm text-app-muted">
			The groups that hold each role on this catalog, including those that inherit it from the
			organization or the platform. Groups you belong to are marked.
		</p>
		<ul class="m-0 grid list-none gap-3 p-0" aria-label="Roles">
			{#each ROLES as role (role)}
				{@const inherited = inheritedFrom(role)}
				<li class="rounded-card border border-app-line bg-app-card px-4 py-3.5">
					<h3 class="m-0 text-sm font-semibold">{ROLE_NAMES[role]}</h3>
					<p class="mt-0.5 mb-0 text-sm text-app-muted">
						Can {ROLE_ABILITIES[role]}.{#if inherited}{' '}{inherited}.{/if}
					</p>
					{#if groups[role].length > 0}
						<ul class="mt-2.5 mb-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Groups">
							{#each groups[role] as group (group)}
								<li class="flex min-w-0 items-center gap-1.5">
									<code class="break-all">{group}</code>
									{#if mine.has(group)}<Badge tone="accent">You</Badge>{/if}
								</li>
							{/each}
						</ul>
					{:else}
						<p class="mt-2.5 mb-0 text-sm text-app-muted">No groups.</p>
					{/if}
				</li>
			{/each}
		</ul>
		{#if can.administerCatalog}
			<div class="mt-6 max-w-3xl">
				<CliHint title="Grant a role, then apply the directory ACLs" command={grantCommand} />
			</div>
		{/if}
	{/if}
</section>
