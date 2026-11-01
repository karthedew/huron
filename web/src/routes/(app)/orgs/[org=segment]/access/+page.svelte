<script lang="ts">
	import { Lock } from '@lucide/svelte';
	import { ORGANIZATION_ROLES, type OrganizationRole } from '$api/types';
	import Badge from '$design/components/Badge.svelte';
	import { displayName } from '$lib/names';
	import { ROLE_ABILITIES, ROLE_NAMES } from '$lib/roles';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const organization = $derived(data.organizationDetails);
	const mine = $derived(new Set(data.user.groups));

	/** What a role granted here allows: the catalog roles hold in every catalog of it. */
	function abilities(role: OrganizationRole): string {
		const text = `Can ${ROLE_ABILITIES[role]}`;
		return role === 'org_admin' ? `${text}.` : `${text}, in every catalog of the organization.`;
	}
</script>

<svelte:head><title>{pageTitle('Access', displayName(organization))}</title></svelte:head>

<section aria-labelledby="organization-access">
	<h2 id="organization-access" class="m-0 border-0 p-0 text-base font-semibold">Who has access</h2>
	{#if data.groups === null}
		<p class="mt-3 mb-0 flex items-center gap-2">
			<Lock size={16} class="shrink-0 text-app-muted" aria-hidden="true" />You don't have permission
			to see this.
		</p>
	{:else}
		{@const groups = data.groups}
		<p class="mt-2 mb-4 max-w-3xl text-sm text-app-muted">
			The groups granted each role on this organization. Catalog administrators, contributors and
			readers granted here hold their role in every catalog of the organization, existing and
			future; a catalog can grant more groups on its own Access tab, not take these away. Groups you
			belong to are marked.
		</p>
		<ul class="m-0 grid list-none gap-3 p-0" aria-label="Roles">
			{#each ORGANIZATION_ROLES as role (role)}
				<li class="rounded-card border border-app-line bg-app-card px-4 py-3.5">
					<h3 class="m-0 text-sm font-semibold">{ROLE_NAMES[role]}</h3>
					<p class="mt-0.5 mb-0 text-sm text-app-muted">{abilities(role)}</p>
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
		{#if organization.declared}
			<p class="mt-6 mb-0 max-w-3xl text-sm">
				These groups are declared in the service configuration, as <code>groups.&lt;role&gt;</code>
				of the organization: an operator changes them there, and the service applies them when it starts.
			</p>
		{/if}
	{/if}
</section>
