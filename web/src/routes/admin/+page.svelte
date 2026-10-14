<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { browseHref } from '$lib/stores/workspace';
	import { ShieldCheck, Users, Database, Settings, Building2 } from '@lucide/svelte';
	import AccessPanel from '$design/components/polaris/AccessPanel.svelte';
	import CatalogSettingsPanel from '$design/components/polaris/CatalogSettingsPanel.svelte';
	import PolarisForm from '$design/components/polaris/PolarisForm.svelte';
	import '$design/polaris.css';
	import type { PageData, ActionData } from './$types';
	let { data, form }: { data: PageData; form: ActionData } = $props();
	const active = $derived(
		['organizations', 'catalogs', 'users', 'access'].includes(data.activeTab)
			? data.activeTab
			: 'catalogs'
	);
	const managedCatalogRoles = ['huron_reader', 'huron_writer', 'huron_catalog_admin'];
	const managedMemberships = $derived(
		Object.fromEntries(data.users.map((user) => [user.polarisPrincipal, user.polarisPrincipalRole]))
	);
	function href(changes: Record<string, string | null>): '/admin' | `/admin?${string}` {
		const query = new URLSearchParams(page.url.searchParams);
		if (data.selectedOrganization) query.set('organization', data.selectedOrganization);
		for (const key of [...query.keys()]) if (key.startsWith('/')) query.delete(key);
		for (const [key, value] of Object.entries(changes))
			value === null ? query.delete(key) : query.set(key, value);
		return query.size ? `/admin?${query}` : '/admin';
	}
</script>

<svelte:head><title>Administration · Huron</title></svelte:head>

<div class="polaris-workspace min-w-0">
	<div class="mb-6">
		<p
			class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-app-muted"
		>
			<ShieldCheck size={15} /> Huron administrator
		</p>
		<h1>Administration</h1>
		<p class="mt-2 text-sm text-app-muted">
			Manage the live Polaris catalogs behind Huron, username/password accounts and Polaris access
			controls.
		</p>
		<p class="mt-2 break-all font-mono text-xs text-app-muted">
			{data.upstream} · realm {data.realm}
		</p>
	</div>
	<nav
		class="mb-5 flex flex-wrap gap-2 border-b border-app-line"
		aria-label="Administration sections"
	>
		{#each [{ id: 'organizations', label: 'Organizations', icon: Building2 }, { id: 'catalogs', label: 'Catalogs', icon: Database }, { id: 'users', label: 'Users', icon: Users }, { id: 'access', label: 'Advanced Polaris access', icon: Settings }] as tab (tab.id)}
			<a
				class={['section-tab', active === tab.id && 'active']}
				href={resolve(href({ tab: tab.id }))}
				aria-current={active === tab.id ? 'page' : undefined}><tab.icon size={16} />{tab.label}</a
			>
		{/each}
	</nav>
	{#if form}<div
			class={[
				'mb-5 rounded-md border p-3 text-sm',
				form.success
					? 'border-app-success/40 bg-brand-soft'
					: 'border-app-danger/40 bg-app-danger/10'
			]}
			role={form.success ? 'status' : 'alert'}
		>
			{form.message}
		</div>{/if}
	{#if form && 'credentials' in form && form.credentials}
		<section class="panel mb-5">
			<h2>Save these Polaris credentials once</h2>
			<p class="hint mb-3">
				Principal {form.credentials.principal}. The secret appears only in this action response.
			</p>
			<dl class="property-list">
				<div>
					<dt>Client ID</dt>
					<dd>{form.credentials.clientId}</dd>
				</div>
				<div>
					<dt>Client secret</dt>
					<dd>{form.credentials.clientSecret}</dd>
				</div>
			</dl>
		</section>
	{/if}
	{#if data.notice}<p class="notice mb-5" role="status">{data.notice}</p>{/if}
	{#each Object.entries(data.errors) as [key, message] (key)}<p
			role="alert"
			class="mb-3 text-sm text-app-danger"
		>
			{message}
		</p>{/each}
	{#if active === 'organizations'}
		<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(280px,420px)]">
			<section class="panel self-start">
				<h2>Organizations</h2>
				<p class="hint mb-4">
					Each organization links to a Polaris realm. Its catalogs and access controls stay within
					that root.
				</p>
				<div class="grid gap-3">
					{#each data.organizations as organization (organization.id)}<article
							class="min-w-0 rounded-md border border-app-line p-4"
						>
							<h3 class="m-0 break-words text-base font-semibold">
								<a
									href={resolve(
										`/settings/organization?organization=${encodeURIComponent(organization.slug)}`
									)}>{organization.name}</a
								>
							</h3>
							<p class="hint mt-1">
								{organization.slug} · realm {organization.realm}
							</p>
							{#if organization.description}<p class="mt-3 break-words text-sm text-app-muted">
									{organization.description}
								</p>{/if}<a
								class="mt-3 inline-block text-sm"
								href={resolve(`/browse?organization=${encodeURIComponent(organization.slug)}`)}
								>View catalogs</a
							>
						</article>{:else}<p class="hint">
							Create your first organization to organize catalogs.
						</p>{/each}
				</div>
			</section>
			<section class="panel self-start">
				<h2>Create organization</h2>
				<PolarisForm
					action="createOrganization"
					submit="Create organization"
					disabled={!data.availableRealms.length}
					><label
						>Organization name<input name="name" required placeholder="Research division" /></label
					><label
						>Organization identifier<input
							name="slug"
							required
							pattern="[a-z0-9][a-z0-9-]*"
							placeholder="research-division"
						/></label
					><label
						>Polaris realm<select name="realm" required
							><option value="">Choose a configured realm</option
							>{#each data.availableRealms as endpoint (endpoint.realm)}<option
									value={endpoint.realm}>{endpoint.realm} · {endpoint.url}</option
								>{/each}</select
						></label
					><label>Description<textarea name="description" rows="3"></textarea></label>
					<p class="hint">
						Use a stable identifier and a configured Polaris realm. Catalogs created in this
						organization belong to that realm.
					</p>
					{#if !data.availableRealms.length}<p class="hint">
							All configured realms already have an organization. Configure another Polaris realm to
							add a new root.
						</p>{/if}</PolarisForm
				>
			</section>
		</div>
	{:else if active === 'catalogs'}
		<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(280px,420px)]">
			<div class="grid min-w-0 gap-5">
				<section class="panel">
					<h2>Polaris catalogs</h2>
					<p class="hint mb-4">
						Catalogs group datasets around a program or data domain. A catalog may contain Raw,
						Iceberg, and Icechunk datasets.
					</p>
					<div class="grid gap-3">
						{#each data.catalogs as catalog (catalog.name)}<div
								class="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-md border border-app-line p-3"
							>
								<div class="min-w-0">
									<strong class="break-all text-sm">{catalog.name}</strong>
									<p class="hint">{catalog.storageConfigInfo.storageType} · {catalog.type}</p>
									<p class="hint">
										{data.organization?.name ?? 'Organization'}
									</p>
								</div>
								<div class="flex flex-wrap gap-3 text-sm">
									<a href={resolve(browseHref(catalog.name, [], '', data.selectedOrganization))}
										>Browse</a
									><a
										href={resolve(
											`/settings/catalog?catalog=${encodeURIComponent(catalog.name)}&organization=${encodeURIComponent(data.selectedOrganization)}`
										)}>Users & settings</a
									><a href={resolve(href({ catalog: catalog.name }))}>Configure</a>
								</div>
							</div>{:else}<p class="hint">
								No catalogs yet. Create your first catalog here.
							</p>{/each}
					</div>
				</section>
				{#if data.catalog}<CatalogSettingsPanel catalog={data.catalog} allowDrop />{/if}
			</div>
			<section class="panel self-start">
				<h2>Create catalog</h2>
				<p class="hint mb-4">
					Create the catalog in Polaris and grant the default Huron administrator metadata, content
					and access management.
				</p>
				<PolarisForm action="createCatalog" submit="Create catalog">
					<label
						>Organization<select name="organization" required value={data.selectedOrganization}
							>{#each data.organizations as organization (organization.id)}<option
									value={organization.slug}>{organization.name}</option
								>{:else}<option value="">Create an organization first</option>{/each}</select
						></label
					><label
						>Catalog name<input
							name="name"
							required
							placeholder="environmental_monitoring"
						/></label
					>
					<label
						>Default repository base URI<input
							name="defaultBaseLocation"
							required
							placeholder="file:///path/to/space/research/"
						/></label
					>
					<label
						>Catalog properties · JSON<textarea name="properties" rows="3" value={'{}'}
						></textarea></label
					>
					<label
						>Storage configuration · JSON<textarea
							name="storageConfigInfo"
							rows="5"
							value={JSON.stringify(
								{ storageType: 'FILE', allowedLocations: ['file:///path/to/space/'] },
								null,
								2
							)}
						></textarea></label
					>
					<p class="hint">
						Set allowedLocations to the storage space used by this catalog. The base URI must fall
						within an allowed location. If setup is interrupted, retry with the same name and
						configuration.
					</p>
				</PolarisForm>
			</section>
		</div>
	{:else if active === 'users'}
		<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(280px,400px)]">
			<section class="panel">
				<h2>Huron users</h2>
				<p class="hint mb-4">
					Every user has their own Polaris principal. Catalog grants determine their scientific
					access.
				</p>
				<div class="grid gap-4">
					{#each data.users as user (user.id)}<div
							class="min-w-0 rounded-md border border-app-line p-4"
						>
							<div class="flex flex-wrap justify-between gap-2">
								<div>
									<h3 class="m-0 text-sm font-semibold">{user.displayName}</h3>
									<p class="hint">
										{user.username} · {user.isAdmin
											? 'Huron administrator'
											: user.disabled
												? 'Disabled'
												: 'Active'}
									</p>
								</div>
								<code class="break-all text-xs text-app-muted">{user.polarisPrincipal}</code>
							</div>
							<div class="my-3 flex flex-wrap gap-2">
								{#each user.catalogMemberships as membership (membership.catalog)}<a
										class="rounded border border-app-line px-2 py-1 text-xs"
										href={resolve(
											`/settings/catalog?catalog=${encodeURIComponent(membership.catalog)}&organization=${encodeURIComponent(data.selectedOrganization)}`
										)}>{membership.catalog} · {membership.roles.join(', ')}</a
									>{:else}<span class="hint">No managed catalog memberships</span>{/each}
							</div>
							<details class="editor">
								<summary>Reset password for {user.username}</summary><PolarisForm
									action="resetPassword"
									submit={`Reset password for ${user.username}`}
									><input type="hidden" name="userId" value={user.id} /><label
										>New password<input
											name="password"
											type="password"
											required
											minlength="12"
											autocomplete="new-password"
										/></label
									>
									<p class="hint">
										Existing Huron sessions are invalidated. Give this password directly to the
										user.
									</p></PolarisForm
								>
							</details>
							{#if !user.isAdmin}<div class="mt-4">
									<PolarisForm
										action="setDisabled"
										submit={user.disabled ? `Enable ${user.username}` : `Disable ${user.username}`}
										danger={!user.disabled}
										><input type="hidden" name="userId" value={user.id} /><input
											type="hidden"
											name="disabled"
											value={user.disabled ? 'false' : 'true'}
										/></PolarisForm
									>
								</div>{/if}
						</div>{/each}
				</div>
			</section>
			<section class="panel self-start">
				<h2>Create user</h2>
				<p class="hint mb-4">
					Create a username/password login, then optionally assign its first catalog. This also adds
					membership in that catalog’s organization.
				</p>
				<PolarisForm action="createUser" submit="Create Huron user"
					><label
						>Username<input
							name="username"
							required
							pattern={'[a-zA-Z0-9][a-zA-Z0-9_.-]{2,63}'}
							autocomplete="off"
						/></label
					><label>Display name<input name="displayName" /></label><label
						>Initial password<input
							name="password"
							type="password"
							required
							minlength="12"
							autocomplete="new-password"
						/></label
					><label
						>Initial catalog<select name="catalog"
							><option value="">No catalog access yet</option
							>{#each data.catalogs as catalog (catalog.name)}<option value={catalog.name}
									>{catalog.name}</option
								>{/each}</select
						></label
					><label
						>Initial role<select name="role"
							><option value="reader">Reader</option><option value="writer">Writer</option><option
								value="admin">Catalog admin</option
							></select
						></label
					></PolarisForm
				>
			</section>
		</div>
	{:else}
		<section class="panel mb-5">
			<h2>Catalog scope</h2>
			<form method="GET" action={resolve('/admin')} class="mt-3 flex flex-wrap items-end gap-3">
				<input type="hidden" name="tab" value="access" /><input
					type="hidden"
					name="organization"
					value={data.selectedOrganization}
				/><label class="min-w-0 flex-1"
					>Catalog<select name="catalog" value={data.selected.catalog}
						>{#each data.catalogs as catalog (catalog.name)}<option value={catalog.name}
								>{catalog.name}</option
							>{/each}</select
					></label
				><button class="secondary" type="submit">Select catalog</button>
			</form>
		</section>
		<AccessPanel
			{data}
			{href}
			managedPrincipals={data.users.map((user) => user.polarisPrincipal)}
			managedPrincipalRoles={data.users.map((user) => user.polarisPrincipalRole)}
			{managedMemberships}
			{managedCatalogRoles}
		/>
	{/if}
</div>
