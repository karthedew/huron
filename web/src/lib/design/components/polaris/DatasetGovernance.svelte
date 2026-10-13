<script lang="ts">
	import { resolve } from '$app/paths';
	import type { PolarisDatasetGovernance } from '$api/types';
	let {
		governance,
		catalog,
		kind,
		href
	}: {
		governance: PolarisDatasetGovernance | null;
		catalog: string;
		kind: 'permissions' | 'policies';
		href: (changes: Record<string, string | null>) => '/browse' | `/browse?${string}`;
	} = $props();
</script>

{#if !governance}<p class="text-sm text-app-muted">
		{kind === 'permissions'
			? 'Permission details are unavailable for this account.'
			: 'Applicable policy information is unavailable.'}
	</p>
{:else if kind === 'permissions'}
	<h2 class="governance-heading">Permissions</h2>
	<p class="mt-3 text-xs leading-5 text-app-muted">{governance.permissions.notice}</p>
	{#if governance.permissions.error}<p role="status" class="mt-3 text-xs text-app-muted">
			{governance.permissions.error}
		</p>{/if}
	<dl class="mt-4 grid gap-3 text-xs">
		<div>
			<dt class="text-app-muted">Your Polaris principal</dt>
			<dd class="mt-1 break-all font-mono">{governance.permissions.principal}</dd>
		</div>
		<div>
			<dt class="text-app-muted">Principal roles</dt>
			<dd class="mt-1 break-all">{governance.permissions.principalRoles.join(', ') || 'None'}</dd>
		</div>
		<div>
			<dt class="text-app-muted">Catalog roles</dt>
			<dd class="mt-1 break-all">{governance.permissions.catalogRoles.join(', ') || 'None'}</dd>
		</div>
	</dl>
	<div class="mt-5 flex flex-wrap gap-2 text-xs">
		{#each [{ name: 'Read metadata', allowed: governance.permissions.capabilities.readMetadata }, { name: 'Read data', allowed: governance.permissions.capabilities.readData }, { name: 'Write data', allowed: governance.permissions.capabilities.writeData }, { name: 'Manage access', allowed: governance.permissions.capabilities.manageAccess }] as capability (capability.name)}<span
				class="rounded border border-app-line px-2 py-1"
				>{capability.name}: {capability.allowed ? 'Granted' : 'Not granted'}</span
			>{/each}
	</div>
	<div class="mt-5 min-w-0 overflow-x-auto" role="region" aria-label="Dataset grants">
		<table class="m-0 w-full text-left text-xs">
			<thead
				><tr class="border-b border-app-line text-app-muted"
					><th class="px-3 py-2 font-medium">Catalog role</th><th class="px-3 py-2 font-medium"
						>Privilege</th
					><th class="px-3 py-2 font-medium">Scope</th><th class="px-3 py-2 font-medium"
						>Inheritance</th
					></tr
				></thead
			><tbody
				>{#each governance.permissions.applicableGrants as entry (`${entry.catalogRole}:${JSON.stringify(entry.grant)}`)}<tr
						class="border-b border-app-line/60"
						><td class="break-all px-3 py-2"
							><details>
								<summary class="text-xs">{entry.catalogRole}</summary>
								<p class="mt-2 text-xs text-app-muted">Assigned principal roles</p>
								<ul class="mt-1 grid list-none gap-1 p-0">
									{#each entry.principalRoles as principalRole (principalRole)}<li
											class="break-all font-mono text-xs"
										>
											{principalRole}
										</li>{:else}<li class="text-xs text-app-muted">None</li>{/each}
								</ul>
							</details></td
						><td class="px-3 py-2 font-mono">{entry.grant.privilege}</td><td
							class="break-all px-3 py-2">{entry.scopeLabel}</td
						><td class="px-3 py-2">{entry.inherited ? 'Inherited' : 'Direct'}</td></tr
					>{:else}<tr
						><td colspan="4" class="px-3 py-6 text-app-muted">No applicable grants disclosed.</td
						></tr
					>{/each}</tbody
			>
		</table>
	</div>
	{#if governance.permissions.capabilities.manageAccess}<a
			class="mt-5 inline-block text-xs font-medium"
			href={resolve(`/settings/catalog?catalog=${encodeURIComponent(catalog)}&tab=access`)}
			>Manage catalog grants →</a
		>{/if}
{:else}
	<h2 class="governance-heading">Policies</h2>
	<p class="mt-3 text-sm leading-6 text-app-muted">{governance.policies.message}</p>
	{#if governance.policies.error}<p role="status" class="mt-3 text-xs text-app-muted">
			{governance.policies.error}
		</p>{/if}
	{#if governance.policies.supported}<ul class="mt-4 grid list-none gap-3 p-0">
			{#each governance.policies.policies as policy (`${JSON.stringify(policy.namespace)}:${policy.name}:${policy.version}`)}<li
					class="rounded border border-app-line p-3"
				>
					<p class="text-sm font-medium">{policy.name}</p>
					<p class="mt-1 text-xs text-app-muted">
						{policy.policyType} · version {policy.version} · {policy.inherited
							? 'Inherited'
							: 'Direct'}
					</p>
					{#if policy.description}<p class="mt-2 text-xs leading-5 text-app-muted">
							{policy.description}
						</p>{/if}
				</li>{:else}<li class="text-xs text-app-muted">
					No applicable policies are disclosed for this table.
				</li>{/each}
		</ul>{/if}
	{#if governance.policies.nextPageToken}<a
			class="mt-4 inline-block text-xs"
			href={resolve(href({ policiesPageToken: governance.policies.nextPageToken }))}
			>Next policies →</a
		>{/if}
{/if}

<style>
	.governance-heading {
		margin: 0;
		padding: 0;
		border: 0;
		font-size: 0.85rem;
		font-weight: 600;
	}
</style>
