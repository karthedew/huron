<script lang="ts">
	import { resolve } from '$app/paths';
	import { Lock } from '@lucide/svelte';
	import type { RoleScope } from '$api/types';
	import Badge from '$design/components/Badge.svelte';
	import { displayName } from '$lib/names';
	import { visibleOrganization } from '$lib/organizations';
	import { ROLE_ABILITIES, ROLE_NAMES } from '$lib/roles';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const catalog = $derived(data.catalog);
	const owner = $derived(visibleOrganization(catalog.organization, data.organizations));
	const ownerName = $derived(owner ? displayName(owner) : catalog.organization);
	const mine = $derived(new Set(data.user.groups));
</script>

<svelte:head><title>{pageTitle('Access', displayName(catalog))}</title></svelte:head>

{#snippet sourceLabel(scope: RoleScope)}
	{#if scope === 'platform'}
		Inherited from the platform
	{:else if scope === 'organization'}
		Inherited from <a
			href={resolve('/(app)/orgs/[org=segment]/access', { org: catalog.organization })}
			class="underline underline-offset-2 hover:decoration-2">{ownerName}</a
		>
	{:else}
		Granted on this catalog
	{/if}
{/snippet}

<section aria-labelledby="catalog-access">
	<h2 id="catalog-access" class="m-0 border-0 p-0 text-base font-semibold">Who has access</h2>
	{#if data.access === null}
		<p class="mt-3 mb-0 flex items-center gap-2">
			<Lock size={16} class="shrink-0 text-app-muted" aria-hidden="true" />You don't have permission
			to see this.
		</p>
	{:else}
		<p class="mt-2 mb-4 max-w-3xl text-sm text-app-muted">
			The groups that hold each role on this catalog, and where each was granted. Groups granted on
			the organization hold their role in every catalog of it; a catalog can grant more groups, not
			take those away. Groups you belong to are marked.
		</p>
		<ul class="m-0 grid list-none gap-3 p-0" aria-label="Roles">
			{#each data.access as { role, sources } (role)}
				<li class="rounded-card border border-app-line bg-app-card px-4 py-3.5">
					<h3 class="m-0 text-sm font-semibold">{ROLE_NAMES[role]}</h3>
					<p class="mt-0.5 mb-0 text-sm text-app-muted">Can {ROLE_ABILITIES[role]}.</p>
					{#if sources.length > 0}
						<dl class="mt-2.5 mb-0 grid gap-2">
							{#each sources as source (source.scope)}
								{@const id = `access-${role}-${source.scope}`}
								<div class="min-w-0">
									<dt {id} class="text-xs font-semibold wrap-anywhere text-app-muted">
										{@render sourceLabel(source.scope)}
									</dt>
									<dd class="m-0 mt-1">
										<ul class="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-labelledby={id}>
											{#each source.groups as group (group)}
												<li class="flex min-w-0 items-center gap-1.5">
													<code class="break-all">{group}</code>
													{#if mine.has(group)}<Badge tone="accent">You</Badge>{/if}
												</li>
											{/each}
										</ul>
									</dd>
								</div>
							{/each}
						</dl>
					{:else}
						<p class="mt-2.5 mb-0 text-sm text-app-muted">No groups.</p>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>
