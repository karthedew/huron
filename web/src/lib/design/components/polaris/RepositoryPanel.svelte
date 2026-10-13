<script lang="ts">
	import { Database, Folder, ChevronRight } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import EmptyState from '$design/components/EmptyState.svelte';
	import PolarisForm from './PolarisForm.svelte';
	import RepositoryOperations from './RepositoryOperations.svelte';
	import type { PolarisActionResult, PolarisIcechunkTable, PolarisWorkspaceData } from '$api/types';

	let {
		data,
		table,
		href,
		showCatalogSelector = true,
		showCatalogControls = true,
		showResourceNavigation = true,
		detailFirst = false
	}: {
		data: PolarisWorkspaceData;
		table: PolarisIcechunkTable | null;
		href: (
			changes: Record<string, string | null>
		) => '/polaris' | `/polaris?${string}` | '/browse' | `/browse?${string}`;
		showCatalogSelector?: boolean;
		showCatalogControls?: boolean;
		showResourceNavigation?: boolean;
		detailFirst?: boolean;
	} = $props();
	let namespaceName = $state('');
	let catalogConfirmation = $state('');
	let namespaceConfirmation = $state('');
	const namespaceJson = $derived(JSON.stringify(data.selected.namespace));
	const namespaceLabel = $derived(data.selected.namespace.join(' / '));
	const namespaceLocation = $derived(data.namespaceProperties?.location ?? '');
	const storageRoot = $derived(data.catalog?.properties['default-base-location'] ?? '');
	const namespaceDropLabel = $derived(data.selected.namespace.join('.'));
	async function rememberTable(result: PolarisActionResult): Promise<void> {
		if (!result.table) return;
		await goto(
			resolve(
				href({ catalog: data.selected.catalog, namespace: namespaceJson, table: result.table.name })
			),
			{ replaceState: true, keepFocus: true, noScroll: true, invalidateAll: true }
		);
	}
</script>

{#snippet repositoryDetails()}
	{#if table && data.selected.catalog && data.selected.namespace.length}
		<section class="panel">
			<div class="section-heading">
				<Database size={19} class="text-brand-strong" />
				<div>
					<h2>{table.name}</h2>
					<p>Icechunk registration details</p>
				</div>
			</div>
			<dl class="property-list">
				<div>
					<dt>Location</dt>
					<dd>{table.location}</dd>
				</div>
				{#each Object.entries(table.properties) as [key, value] (key)}<div>
						<dt>{key}</dt>
						<dd>{value}</dd>
					</div>{/each}
			</dl>
			<RepositoryOperations {data} {table} />
		</section>
	{/if}
{/snippet}

<div class="grid min-w-0 gap-5">
	{#if detailFirst}{@render repositoryDetails()}{/if}
	{#if showCatalogSelector || showCatalogControls}
		<section class="panel">
			<div class="section-heading">
				<Database size={19} class="text-brand-strong" />
				<div>
					<h2>Catalog</h2>
					<p>Select a live Polaris catalog to browse its repositories.</p>
				</div>
			</div>
			{#if data.catalogs.length}
				<form method="GET" action={page.url.pathname} class="flex flex-wrap items-end gap-3">
					<input type="hidden" name="tab" value="repositories" />
					<label class="min-w-0 flex-1"
						>Catalog
						<select name="catalog" value={data.selected.catalog}>
							<option value="">Choose a catalog</option>
							{#each data.catalogs as catalog (catalog.name)}<option value={catalog.name}
									>{catalog.name}</option
								>{/each}
						</select>
					</label>
					<button type="submit" class="secondary">Open catalog</button>
				</form>
			{:else}
				<EmptyState
					title={data.errors.catalogs ? 'Catalog listing unavailable' : 'No catalogs available'}
					detail="Open a resource by name below, or create a catalog if your principal has management access."
				/>
			{/if}
			<details class="editor" open={!data.catalogs.length}>
				<summary>Open a catalog or repository by name</summary>
				<form method="GET" action={page.url.pathname} class="grid gap-3">
					<input type="hidden" name="tab" value="repositories" />
					<label
						>Catalog name<input
							name="catalog"
							required
							value={data.selected.catalog}
							placeholder="huron_local"
						/></label
					>
					<label
						>Namespace levels · JSON array<input
							name="namespace"
							value={namespaceJson}
							placeholder="[&quot;science&quot;]"
						/></label
					>
					<label
						>Icechunk table name · optional<input
							name="table"
							value={data.selected.table}
							placeholder="temperature"
						/></label
					>
					<p class="hint">
						Open an exact resource when your principal can access it but cannot list catalogs or
						namespaces.
					</p>
					<button type="submit" class="secondary w-fit">Open resource</button>
				</form>
			</details>
			{#if showCatalogControls}
				<details class="editor">
					<summary>Create a catalog</summary>
					<PolarisForm action="createCatalog" submit="Create catalog">
						<label>Catalog name<input name="name" required placeholder="science" /></label>
						<label
							>Default base location<input
								name="defaultBaseLocation"
								required
								placeholder="file:///path/to/icechunk/"
							/></label
						>
						<label
							>Storage configuration · JSON<textarea
								name="storageConfigInfo"
								required
								rows="4"
								placeholder={'{"storageType":"FILE","allowedLocations":["file:///path/to/icechunk/"]}'}
							></textarea></label
						>
						<label
							>Catalog properties · JSON<textarea
								name="properties"
								rows="4"
								value={'{"polaris.config.allow.client-specified.table.location":"true"}'}
							></textarea></label
						>
						<p class="hint">
							Use the storage configuration for your deployment. FILE catalogs use local storage and
							do not vend credentials.
						</p>
					</PolarisForm>
				</details>
			{/if}
			{#if data.catalog}
				<div class="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-app-muted">
					<span
						>Storage: <strong class="text-app-fg"
							>{data.catalog.storageConfigInfo.storageType}</strong
						></span
					>
					<span>Base: <code class="break-all">{storageRoot || 'Not configured'}</code></span>
				</div>
				{#if data.catalog.storageConfigInfo.storageType === 'FILE'}
					<p class="notice">
						Local FILE storage does not vend credentials. Repository access depends on filesystem
						permissions on the machine running your Python client.
					</p>
				{/if}
				{#if showCatalogControls}
					<details class="editor">
						<summary>Catalog configuration</summary>
						<PolarisForm action="updateCatalog" submit="Save catalog configuration">
							<input type="hidden" name="catalog" value={data.selected.catalog} />
							<input type="hidden" name="name" value={data.selected.catalog} />
							<input
								type="hidden"
								name="currentEntityVersion"
								value={data.catalog.entityVersion ?? ''}
							/>
							<label
								>Catalog properties · JSON<textarea
									name="properties"
									rows="5"
									value={JSON.stringify(data.catalog.properties, null, 2)}
								></textarea></label
							>
							<label
								>Storage configuration · JSON<textarea
									name="storageConfigInfo"
									rows="5"
									value={JSON.stringify(data.catalog.storageConfigInfo, null, 2)}
								></textarea></label
							>
						</PolarisForm>
					</details>
					<details class="editor">
						<summary class="text-app-danger">Drop catalog</summary>
						<PolarisForm
							action="deleteCatalog"
							submit="Drop catalog"
							danger
							disabled={catalogConfirmation !== data.selected.catalog}
						>
							<input type="hidden" name="catalog" value={data.selected.catalog} />
							<input type="hidden" name="name" value={data.selected.catalog} />
							<p class="hint">
								This removes the catalog from Polaris. Polaris will reject the operation if it
								contains namespaces or tables.
							</p>
							<label
								>Type {data.selected.catalog} to confirm<input
									name="confirmation"
									bind:value={catalogConfirmation}
									required
								/></label
							>
						</PolarisForm>
					</details>
				{/if}
			{/if}
		</section>
	{/if}

	{#if data.selected.catalog}
		<section class="panel">
			<div class="section-heading">
				<Folder size={19} class="text-brand-strong" />
				<div>
					<h2>Namespaces</h2>
					<p>Browse hierarchy and namespace properties.</p>
				</div>
			</div>
			{#if showResourceNavigation}
				<nav
					class="mb-4 flex flex-wrap items-center gap-2 text-sm"
					aria-label="Polaris namespace breadcrumbs"
				>
					<a
						href={resolve(
							href({ namespace: null, table: null, pageToken: null, namespacePageToken: null })
						)}>{data.selected.catalog}</a
					>
					{#each data.selected.namespace as level, index (JSON.stringify(data.selected.namespace.slice(0, index + 1)))}
						<ChevronRight size={13} aria-hidden="true" />
						<a
							href={resolve(
								href({
									namespace: JSON.stringify(data.selected.namespace.slice(0, index + 1)),
									table: null,
									pageToken: null,
									namespacePageToken: null
								})
							)}>{level}</a
						>
					{/each}
				</nav>
				{#if data.namespaces.length}
					<ul class="grid gap-2 sm:grid-cols-2">
						{#each data.namespaces as namespace (JSON.stringify(namespace))}
							<li>
								<a
									class="resource-link"
									href={resolve(
										href({
											namespace: JSON.stringify(namespace),
											table: null,
											pageToken: null,
											namespacePageToken: null
										})
									)}
									><Folder size={16} /><span class="break-all">{namespace.join(' / ')}</span
									><ChevronRight size={15} class="ml-auto shrink-0" /></a
								>
							</li>
						{/each}
					</ul>
				{:else}
					<p class="hint">No child namespaces are visible here.</p>
				{/if}
				{#if data.nextNamespacePageToken}
					<nav
						class="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm"
						aria-label="Namespace pagination"
					>
						<a href={resolve(href({ namespacePageToken: null }))}>First namespace page</a>
						<a href={resolve(href({ namespacePageToken: data.nextNamespacePageToken }))}
							>Next namespace page →</a
						>
					</nav>
				{/if}
			{/if}
			<details class="editor">
				<summary
					>Create {data.selected.namespace.length ? 'a child namespace' : 'a namespace'}</summary
				>
				<PolarisForm action="createNamespace" submit="Create namespace">
					<input type="hidden" name="catalog" value={data.selected.catalog} />
					<input
						type="hidden"
						name="namespace"
						value={JSON.stringify([...data.selected.namespace, namespaceName.trim()])}
					/>
					<label
						>Namespace name<input
							bind:value={namespaceName}
							required
							placeholder="experiments"
						/></label
					>
					<label
						>Namespace properties · JSON<textarea name="properties" rows="3" value={'{}'}
						></textarea></label
					>
					<p class="hint">
						Optional <code>location</code> sets the namespace storage root within the catalog’s allowed
						locations.
					</p>
				</PolarisForm>
			</details>
			{#if data.selected.namespace.length && data.namespaceProperties}
				<details class="editor">
					<summary>Properties for {namespaceLabel}</summary>
					<dl class="property-list">
						{#each Object.entries(data.namespaceProperties) as [key, value] (key)}<div>
								<dt>{key}</dt>
								<dd>{value}</dd>
							</div>{/each}
					</dl>
					<PolarisForm action="updateNamespace" submit="Update namespace properties">
						<input type="hidden" name="catalog" value={data.selected.catalog} />
						<input type="hidden" name="namespace" value={namespaceJson} />
						<label
							>Set properties · JSON<textarea
								name="updates"
								rows="4"
								value={JSON.stringify(data.namespaceProperties, null, 2)}
							></textarea></label
						>
						<label
							>Remove property names · one per line<textarea
								name="removals"
								rows="2"
								placeholder="description"
							></textarea></label
						>
					</PolarisForm>
				</details>
				<details class="editor">
					<summary class="text-app-danger">Drop namespace</summary>
					<PolarisForm
						action="deleteNamespace"
						submit="Drop namespace"
						danger
						disabled={namespaceConfirmation !== namespaceDropLabel}
					>
						<input type="hidden" name="catalog" value={data.selected.catalog} />
						<input type="hidden" name="namespace" value={namespaceJson} />
						<p class="hint">The namespace must be empty. Repository contents remain in storage.</p>
						<label
							>Type {namespaceDropLabel} to confirm<input
								name="confirmation"
								bind:value={namespaceConfirmation}
								required
							/></label
						>
					</PolarisForm>
				</details>
			{/if}
		</section>

		{#if data.selected.namespace.length}
			<section class="panel">
				<div class="section-heading">
					<Database size={19} class="text-brand-strong" />
					<div>
						<h2>Icechunk repositories</h2>
						<p>Live registrations in {namespaceLabel}.</p>
					</div>
				</div>
				{#if showResourceNavigation}
					{#if data.tables.length}
						<ul class="grid gap-2">
							{#each data.tables as repository (repository.name)}
								<li>
									<a
										class="resource-link"
										href={resolve(href({ table: repository.name }))}
										aria-current={table?.name === repository.name ? 'page' : undefined}
										><Database size={16} /><span class="break-all">{repository.name}</span><span
											class="ml-auto shrink-0 text-xs text-app-muted">Load details</span
										></a
									>
								</li>
							{/each}
						</ul>
					{:else if !data.errors.tables}
						<EmptyState
							title="No Icechunk repositories"
							detail="Register a repository location below to make it discoverable through Polaris."
						/>
					{/if}
					{#if data.nextPageToken || data.tables.length}
						<nav
							class="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm"
							aria-label="Icechunk pagination"
						>
							<a href={resolve(href({ pageToken: null, table: null }))}>First page</a>
							{#if data.nextPageToken}<a
									href={resolve(href({ pageToken: data.nextPageToken, table: null }))}
									>Next page →</a
								>{/if}
						</nav>
					{/if}
				{/if}
				<details class="editor">
					<summary>Register an Icechunk repository</summary>
					<PolarisForm action="createTable" submit="Register repository" onSuccess={rememberTable}>
						<input type="hidden" name="catalog" value={data.selected.catalog} />
						<input type="hidden" name="namespace" value={namespaceJson} />
						<label
							>Repository name<input name="name" required placeholder="simulation-output" /></label
						>
						<label
							>Repository root URI<input
								name="location"
								required
								placeholder={`${namespaceLocation || storageRoot || 'file:///path/to/icechunk/'}simulation-output/`}
							/></label
						>
						<label
							>Repository properties · JSON<textarea name="properties" rows="3" value={'{}'}
							></textarea></label
						>
						<label class="checkbox"
							><input name="delegate" type="checkbox" /><span
								>Request delegated read-write access for initialization</span
							></label
						>
						<p class="hint">
							Registers metadata only. Initialize the repository with Icechunk in Python. Its
							location becomes immutable; properties cannot contain <code>location</code> or keys
							beginning <code>polaris.</code>.
						</p>
						<p class="hint">
							Delegation requires TABLE_WRITE_DATA and a storage provider that supports vending. If
							vending fails after registration, the registration may still exist; refresh the list
							before retrying.
						</p>
					</PolarisForm>
				</details>
				<details class="editor">
					<summary>Load a repository by name</summary>
					<PolarisForm action="loadTable" submit="Load repository" onSuccess={rememberTable}>
						<input type="hidden" name="catalog" value={data.selected.catalog} />
						<input type="hidden" name="namespace" value={namespaceJson} />
						<label>Repository name<input name="name" required value={data.selected.table} /></label>
						<label class="checkbox"
							><input name="delegate" type="checkbox" /><span
								>Check delegated storage access while loading</span
							></label
						>
						<label
							>Access mode<select name="accessMode"
								><option value="read">Read only</option><option value="read-write"
									>Read and write · includes deleting history</option
								></select
							></label
						>
					</PolarisForm>
				</details>
			</section>
		{/if}
	{/if}

	{#if !detailFirst}{@render repositoryDetails()}{/if}
</div>
