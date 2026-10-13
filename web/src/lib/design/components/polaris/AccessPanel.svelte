<script lang="ts">
	import { ShieldCheck, UserRound, UsersRound } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import PolarisForm from './PolarisForm.svelte';
	import type { PolarisGrant, PolarisNamedEntity, PolarisWorkspaceData } from '$api/types';

	let {
		data,
		href,
		realmAdmin = true,
		managedPrincipals = [],
		managedPrincipalRoles = [],
		managedCatalogRoles = [],
		managedMemberships = {}
	}: {
		data: PolarisWorkspaceData;
		href: (
			changes: Record<string, string | null>
		) =>
			| '/polaris'
			| `/polaris?${string}`
			| '/admin'
			| `/admin?${string}`
			| '/settings/catalog'
			| `/settings/catalog?${string}`;
		realmAdmin?: boolean;
		managedPrincipals?: string[];
		managedPrincipalRoles?: string[];
		managedCatalogRoles?: string[];
		managedMemberships?: Record<string, string>;
	} = $props();
	let principalConfirmation = $state('');
	let principalRoleConfirmation = $state('');
	let catalogRoleConfirmation = $state('');
	let grantType = $state<'catalog' | 'namespace' | 'table'>('table');
	const principal = $derived(data.principals.find((item) => item.name === data.selected.principal));
	const principalRole = $derived(
		data.principalRoles.find((item) => item.name === data.selected.principalRole)
	);
	const catalogRole = $derived(
		data.catalogRoles.find((item) => item.name === data.selected.catalogRole)
	);
	const namespaceJson = $derived(JSON.stringify(data.selected.namespace));

	function grantKey(grant: PolarisGrant): string {
		return JSON.stringify([
			grant.type,
			grant.privilege,
			grant.namespace,
			grant.tableName,
			grant.viewName,
			grant.policyName,
			grant.semanticModelName
		]);
	}
	function supportedGrant(grant: PolarisGrant): boolean {
		return ['catalog', 'namespace', 'table'].includes(grant.type);
	}
</script>

{#snippet entityFields(entity?: PolarisNamedEntity)}
	{#if entity}
		<input type="hidden" name="name" value={entity.name} />
		<input type="hidden" name="currentEntityVersion" value={entity.entityVersion ?? ''} />
	{:else}
		<label>Name<input name="name" required /></label>
	{/if}
	<label
		>Properties · JSON<textarea
			name="properties"
			rows="3"
			value={JSON.stringify(entity?.properties ?? {}, null, 2)}
		></textarea></label
	>
{/snippet}

{#snippet catalogContext()}
	<input type="hidden" name="catalog" value={data.selected.catalog} />
{/snippet}

<div class="grid min-w-0 gap-5">
	<div class="notice m-0">
		Polaris access follows <strong
			>principal → principal role → catalog role → resource grants</strong
		>. These operations update live Polaris permissions for Icechunk catalogs and repositories.
	</div>

	{#if realmAdmin}
		<div class="grid min-w-0 gap-5 xl:grid-cols-2">
			<section class="panel">
				<div class="section-heading">
					<UserRound size={19} class="text-brand-strong" />
					<div>
						<h2>Principals</h2>
						<p>Manage identities and their credentials.</p>
					</div>
				</div>
				{#if data.principals.length}
					<ul class="resource-list">
						{#each data.principals as item (item.name)}
							<li>
								<a
									class="resource-link"
									href={resolve(href({ principal: item.name }))}
									aria-current={item.name === data.selected.principal ? 'page' : undefined}
									><UserRound size={15} /><span class="break-all">{item.name}</span><span
										class="ml-auto text-xs text-app-muted">Select</span
									></a
								>
							</li>
						{/each}
					</ul>
				{:else}<p class="hint">No principals available to your current identity.</p>{/if}
				<details class="editor">
					<summary>Create principal</summary>
					<PolarisForm action="createPrincipal" submit="Create principal">
						{@render entityFields()}
						<label class="checkbox"
							><input name="credentialRotationRequired" type="checkbox" /><span
								>Require credential rotation before use</span
							></label
						>
						<p class="hint">
							The generated credentials are shown once. Save them securely before leaving this page.
							A new principal needs role assignments before it can use a catalog.
						</p>
					</PolarisForm>
				</details>
				{#if principal}
					<div class="mt-4 border-t border-app-line pt-4">
						<h3 class="m-0 text-base font-semibold">{principal.name}</h3>
						<p class="hint mt-1">
							Client ID: <code class="break-all"
								>{principal.clientId ?? 'Not returned by Polaris'}</code
							>
						</p>
					</div>
					{#if !managedPrincipals.includes(principal.name)}<details class="editor">
							<summary>Edit principal properties</summary><PolarisForm
								action="updatePrincipal"
								submit="Save principal">{@render entityFields(principal)}</PolarisForm
							>
						</details>{/if}
					{#if managedPrincipals.includes(principal.name)}<p class="notice">
							This principal is connected to a Huron login. Change its password or disable that
							login from the Users tab. Huron retains its Polaris credentials on the server.
						</p>{:else}
						<details class="editor">
							<summary>Rotate or reset credentials</summary>
							<p class="hint mb-3">
								Each action generates new credentials and is not idempotent. Save the returned
								secret and update the principal’s clients. Changing the connected principal’s
								credentials can require signing in again.
							</p>
							<div class="grid gap-3 sm:grid-cols-2">
								<PolarisForm action="rotatePrincipal" submit="Rotate credentials"
									><input type="hidden" name="name" value={principal.name} /></PolarisForm
								>
								<PolarisForm action="resetPrincipal" submit="Reset credentials" danger
									><input type="hidden" name="name" value={principal.name} /></PolarisForm
								>
							</div>
						</details>
					{/if}
					<h3 class="mb-3 text-sm font-semibold">Principal role membership</h3>
					{#if data.principalMemberships.length}
						<ul class="grid gap-3">
							{#each data.principalMemberships as membership (membership.name)}
								<li class="membership-row">
									<span class="break-all">{membership.name}</span
									>{#if managedPrincipals.includes(principal.name) || managedPrincipalRoles.includes(membership.name) || managedMemberships[principal.name] === membership.name}<span
											class="hint">Required by this Huron login</span
										>{:else}<PolarisForm
											action="revokePrincipalRole"
											submit={`Remove ${membership.name}`}
											danger
											><input type="hidden" name="principal" value={principal.name} /><input
												type="hidden"
												name="principalRole"
												value={membership.name}
											/></PolarisForm
										>{/if}
								</li>
							{/each}
						</ul>
					{:else}<p class="hint">No principal roles assigned.</p>{/if}
					{#if !managedPrincipals.includes(principal.name)}<details class="editor">
							<summary>Assign a principal role</summary>
							<PolarisForm
								action="assignPrincipalRole"
								submit="Assign principal role"
								disabled={!data.principalRoles.length}
							>
								<input type="hidden" name="principal" value={principal.name} />
								<label
									>Principal role<select name="principalRole" required
										><option value="">Choose a role</option
										>{#each data.principalRoles.filter((candidate) => !managedPrincipalRoles.includes(candidate.name)) as role (role.name)}<option
												value={role.name}>{role.name}</option
											>{/each}</select
									></label
								>
							</PolarisForm>
						</details>{/if}
					{#if !managedPrincipals.includes(principal.name)}
						<details class="editor">
							<summary class="text-app-danger">Delete principal</summary>
							<PolarisForm
								action="deletePrincipal"
								submit="Delete principal"
								danger
								disabled={principalConfirmation !== principal.name}
							>
								<input type="hidden" name="name" value={principal.name} />
								<p class="hint">
									Removes this identity from Polaris. Clients using its credentials will lose
									access.
								</p>
								<label
									>Type {principal.name} to confirm<input
										name="confirmation"
										bind:value={principalConfirmation}
										required
									/></label
								>
							</PolarisForm>
						</details>
					{/if}
				{/if}
			</section>

			<section class="panel">
				<div class="section-heading">
					<UsersRound size={19} class="text-brand-strong" />
					<div>
						<h2>Principal roles</h2>
						<p>Group identities and assign catalog roles.</p>
					</div>
				</div>
				{#if data.principalRoles.length}
					<ul class="resource-list">
						{#each data.principalRoles as role (role.name)}<li>
								<a
									class="resource-link"
									href={resolve(href({ principalRole: role.name }))}
									aria-current={role.name === data.selected.principalRole ? 'page' : undefined}
									><UsersRound size={15} /><span class="break-all">{role.name}</span
									>{#if role.federated}<span class="ml-auto text-xs text-app-muted">Federated</span
										>{/if}</a
								>
							</li>{/each}
					</ul>
				{:else}<p class="hint">No principal roles available.</p>{/if}
				<details class="editor">
					<summary>Create principal role</summary>
					<PolarisForm action="createPrincipalRole" submit="Create principal role">
						{@render entityFields()}
						<label class="checkbox"
							><input name="federated" type="checkbox" /><span
								>Federated role managed by an identity provider</span
							></label
						>
					</PolarisForm>
				</details>
				{#if principalRole}
					<div class="mt-4 border-t border-app-line pt-4">
						<h3 class="m-0 text-base font-semibold">{principalRole.name}</h3>
					</div>
					{#if !managedPrincipalRoles.includes(principalRole.name)}<details class="editor">
							<summary>Edit principal role properties</summary><PolarisForm
								action="updatePrincipalRole"
								submit="Save principal role">{@render entityFields(principalRole)}</PolarisForm
							>
						</details>{/if}
					<h3 class="mb-3 text-sm font-semibold">
						Catalog roles in {data.selected.catalog || 'the selected catalog'}
					</h3>
					{#if !data.selected.catalog}<p class="hint">
							Choose a catalog in the Repositories section to manage catalog role assignments.
						</p>
					{:else}
						{#if data.catalogAssignments.length}
							<ul class="grid gap-3">
								{#each data.catalogAssignments as assignment (assignment.name)}
									<li class="membership-row">
										<span class="break-all">{assignment.name}</span
										>{#if managedCatalogRoles.includes(assignment.name)}<span class="hint"
												>Manage from catalog users</span
											>{:else}<PolarisForm
												action="revokeCatalogRole"
												submit={`Remove ${assignment.name}`}
												danger
												>{@render catalogContext()}<input
													type="hidden"
													name="principalRole"
													value={principalRole.name}
												/><input
													type="hidden"
													name="catalogRole"
													value={assignment.name}
												/></PolarisForm
											>{/if}
									</li>
								{/each}
							</ul>
						{:else}<p class="hint">No catalog roles assigned in this catalog.</p>{/if}
						<details class="editor">
							<summary>Assign a catalog role</summary>
							<PolarisForm
								action="assignCatalogRole"
								submit="Assign catalog role"
								disabled={!data.catalogRoles.length}
							>
								{@render catalogContext()}
								<input type="hidden" name="principalRole" value={principalRole.name} />
								<label
									>Catalog role<select name="catalogRole" required
										><option value="">Choose a role</option
										>{#each data.catalogRoles.filter((item) => !managedCatalogRoles.includes(item.name)) as role (role.name)}<option
												value={role.name}>{role.name}</option
											>{/each}</select
									></label
								>
							</PolarisForm>
						</details>
					{/if}
					{#if managedPrincipalRoles.includes(principalRole.name)}<p class="notice">
							This role belongs to a Huron login and must remain assigned to that user. Manage the
							login from the Users tab.
						</p>{:else}
						<details class="editor">
							<summary class="text-app-danger">Delete principal role</summary>
							<PolarisForm
								action="deletePrincipalRole"
								submit="Delete principal role"
								danger
								disabled={principalRoleConfirmation !== principalRole.name}
							>
								<input type="hidden" name="name" value={principalRole.name} />
								<p class="hint">
									Removes this role and changes access for principals that rely on it.
								</p>
								<label
									>Type {principalRole.name} to confirm<input
										name="confirmation"
										bind:value={principalRoleConfirmation}
										required
									/></label
								>
							</PolarisForm>
						</details>
					{/if}
				{/if}
			</section>
		</div>
	{/if}

	<section class="panel">
		<div class="section-heading">
			<ShieldCheck size={19} class="text-brand-strong" />
			<div>
				<h2>Catalog roles and grants</h2>
				<p>Privileges for {data.selected.catalog || 'a selected catalog'}.</p>
			</div>
		</div>
		{#if !data.selected.catalog}
			<p class="hint">Select a catalog in the Repositories section to manage its permissions.</p>
		{:else}
			{#if data.catalogRoles.length}
				<ul class="grid gap-2 sm:grid-cols-2">
					{#each data.catalogRoles as role (role.name)}<li>
							<a
								class="resource-link"
								href={resolve(href({ catalogRole: role.name }))}
								aria-current={role.name === data.selected.catalogRole ? 'page' : undefined}
								><ShieldCheck size={15} /><span class="break-all">{role.name}</span></a
							>
						</li>{/each}
				</ul>
			{:else}<p class="hint">No catalog roles available.</p>{/if}
			<details class="editor">
				<summary>Create catalog role</summary><PolarisForm
					action="createCatalogRole"
					submit="Create catalog role"
					>{@render catalogContext()}{@render entityFields()}</PolarisForm
				>
			</details>
			{#if catalogRole}
				<div class="mt-4 border-t border-app-line pt-4">
					<h3 class="m-0 text-base font-semibold">{catalogRole.name}</h3>
				</div>
				{#if !managedCatalogRoles.includes(catalogRole.name)}
					<details class="editor">
						<summary>Edit catalog role properties</summary><PolarisForm
							action="updateCatalogRole"
							submit="Save catalog role"
							>{@render catalogContext()}{@render entityFields(catalogRole)}</PolarisForm
						>
					</details>
				{:else}<p class="notice">
						This fixed role implements Huron catalog membership. Assign Reader, Writer or Catalog
						admin from the Users tab. Use a separate custom role for advanced grants.
					</p>{/if}
				<h3 class="mb-3 text-sm font-semibold">Existing grants</h3>
				{#if data.grants.length}
					<ul class="grid gap-3">
						{#each data.grants as grant (grantKey(grant))}
							<li class="grant-row">
								<div class="min-w-0">
									<p class="break-all font-mono text-xs font-semibold">{grant.privilege}</p>
									<p class="hint mt-1">
										{grant.type} · {data.selected.catalog}{grant.namespace?.length
											? ` / ${grant.namespace.join(' / ')}`
											: ''}{grant.tableName ? ` / ${grant.tableName}` : ''}{grant.viewName
											? ` / ${grant.viewName}`
											: ''}{grant.policyName
											? ` / ${grant.policyName}`
											: ''}{grant.semanticModelName ? ` / ${grant.semanticModelName}` : ''}
									</p>
								</div>
								{#if supportedGrant(grant) && !managedCatalogRoles.includes(catalogRole.name)}
									<details>
										<summary class="text-sm text-app-danger">Revoke</summary>
										<div class="pt-3">
											<PolarisForm action="revokeGrant" submit="Revoke grant" danger
												>{@render catalogContext()}<input
													type="hidden"
													name="catalogRole"
													value={catalogRole.name}
												/><input type="hidden" name="type" value={grant.type} /><input
													type="hidden"
													name="privilege"
													value={grant.privilege}
												/><input
													type="hidden"
													name="namespace"
													value={JSON.stringify(grant.namespace ?? [])}
												/><input
													type="hidden"
													name="tableName"
													value={grant.tableName ?? ''}
												/><label class="checkbox"
													><input name="cascade" type="checkbox" /><span
														>Cascade dependent grants</span
													></label
												>
												<p class="hint">
													Cascading can revoke grants that depend on this privilege.
												</p></PolarisForm
											>
										</div>
									</details>
								{:else}<span class="hint">Manage this resource type through its Polaris API.</span
									>{/if}
							</li>
						{/each}
					</ul>
				{:else}<p class="hint">No grants on this catalog role.</p>{/if}
				{#if !managedCatalogRoles.includes(catalogRole.name)}
					<details class="editor">
						<summary>Add a resource grant</summary>
						<PolarisForm action="addGrant" submit="Add grant">
							{@render catalogContext()}
							<input type="hidden" name="catalogRole" value={catalogRole.name} />
							<div class="grid gap-3 sm:grid-cols-2">
								<label
									>Resource scope<select name="type" bind:value={grantType}
										><option value="catalog">Whole catalog</option><option value="namespace"
											>Namespace</option
										><option value="table">Exact Icechunk table</option></select
									></label
								>
								{#key grantType}<label
										>Privilege<select name="privilege" required
											>{#each data.privileges[grantType] as privilege (privilege)}<option
													value={privilege}>{privilege}</option
												>{/each}</select
										></label
									>{/key}
							</div>
							{#if grantType !== 'catalog'}<label
									>Namespace levels · JSON array<textarea
										name="namespace"
										rows="2"
										value={namespaceJson}
										placeholder="[&quot;science&quot;]"
									></textarea></label
								>{/if}
							{#if grantType === 'table'}<label
									>Exact Icechunk table name<input
										name="tableName"
										required
										value={data.selected.table}
									/></label
								>{/if}
							<p class="hint">
								TABLE_READ_DATA permits read credential requests; TABLE_WRITE_DATA permits explicit
								read-write requests, including deleting repository history. These privileges do not
								add snapshot, branch, or commit APIs to Polaris.
							</p>
						</PolarisForm>
					</details>
					<details class="editor">
						<summary class="text-app-danger">Delete catalog role</summary>
						<PolarisForm
							action="deleteCatalogRole"
							submit="Delete catalog role"
							danger
							disabled={catalogRoleConfirmation !== catalogRole.name}
						>
							{@render catalogContext()}
							<input type="hidden" name="name" value={catalogRole.name} />
							<p class="hint">
								Removing this role changes access for all principal roles assigned to it.
							</p>
							<label
								>Type {catalogRole.name} to confirm<input
									name="confirmation"
									bind:value={catalogRoleConfirmation}
									required
								/></label
							>
						</PolarisForm>
					</details>
				{/if}
			{/if}
		{/if}
	</section>
</div>
