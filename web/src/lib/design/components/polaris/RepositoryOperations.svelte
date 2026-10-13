<script lang="ts">
	import type { IcechunkInspection, PolarisIcechunkTable, PolarisWorkspaceData } from '$api/types';
	import PolarisForm from './PolarisForm.svelte';
	let {
		data,
		table,
		inspection = null
	}: {
		data: PolarisWorkspaceData;
		table: PolarisIcechunkTable;
		inspection?: IcechunkInspection | null;
	} = $props();
	let confirmation = $state('');
	let accessMode = $state('read');
	const namespaceJson = $derived(JSON.stringify(data.selected.namespace));
	const isFile = $derived(table.location.startsWith('file:'));
	const credentialEndpoint = $derived(
		`${data.upstream}/api/catalog/polaris/v1/${encodeURIComponent(data.selected.catalog)}/namespaces/${encodeURIComponent(data.selected.namespace.join('\u001f'))}/icechunk-tables/${encodeURIComponent(table.name)}/credentials?access-mode=read`
	);
	const selection = $derived(
		inspection?.snapshot ? `snapshot_id=${JSON.stringify(inspection.snapshot.id)}` : 'branch="main"'
	);
	const python = $derived(
		`from urllib.parse import urlparse, unquote\nimport icechunk\nimport zarr\n\nlocation = urlparse(${JSON.stringify(table.location)})\nstorage = icechunk.local_filesystem_storage(unquote(location.path))\nrepo = icechunk.Repository.open(storage)\nsession = repo.readonly_session(${selection})\ngroup = zarr.open_group(store=session.store, mode="r")\nprint(group.tree())`
	);
</script>

<div class="grid min-w-0 gap-5">
	<details>
		<summary class="text-sm font-medium">Storage access</summary>
		<div class="mt-4">
			<PolarisForm action="tableCredentials" submit="Check storage access">
				<input type="hidden" name="catalog" value={data.selected.catalog} /><input
					type="hidden"
					name="namespace"
					value={namespaceJson}
				/><input type="hidden" name="name" value={table.name} />
				<label
					>Requested access<select name="accessMode" bind:value={accessMode}
						><option value="read">Read only</option><option value="read-write"
							>Read and write</option
						></select
					></label
				>
				<p class="hint">
					{accessMode === 'read-write'
						? 'Write access includes writing and deleting the repository prefix and history. Requires TABLE_WRITE_DATA.'
						: 'Read access requires TABLE_READ_DATA.'} Polaris authorizes every check. Storage secrets
					stay on the server.
				</p>
			</PolarisForm>
		</div>
	</details>
	<details>
		<summary class="text-sm font-medium">Open in Python</summary>
		<div class="mt-4 grid min-w-0 gap-3">
			{#if isFile}
				<p class="hint">
					Install <code>icechunk</code> and <code>zarr</code> in your Python environment. Run this on
					a machine with access to the repository directory. Filesystem permissions govern direct FILE
					access; no Polaris credentials are needed.
				</p>
				{#if inspection?.snapshot}<p class="hint">
						This example opens the exact snapshot displayed in this view.
					</p>{/if}
				<pre class="m-0 overflow-x-auto text-xs"><code>{python}</code></pre>
			{:else}
				<p class="hint">
					Ask a catalog administrator for a separately provisioned Polaris engine principal scoped
					to this repository. Huron username/password credentials cannot authenticate an external
					Python client. Use those engine credentials with Polaris OAuth and configure Icechunk with
					the vended storage settings.
				</p>
				<code class="break-all text-xs">{credentialEndpoint}</code>
			{/if}
		</div>
	</details>
	<details class="border-t border-app-line pt-4">
		<summary class="text-sm font-medium text-app-danger">Unregister repository</summary>
		<div class="mt-4">
			<PolarisForm
				action="deleteTable"
				submit="Unregister repository"
				danger
				disabled={confirmation !== table.name}
			>
				<input type="hidden" name="catalog" value={data.selected.catalog} /><input
					type="hidden"
					name="namespace"
					value={namespaceJson}
				/><input type="hidden" name="name" value={table.name} />
				<p class="hint">
					Removes the Polaris registration. The repository, data and history in storage remain
					untouched.
				</p>
				<label
					>Type {table.name} to confirm<input
						name="confirmation"
						bind:value={confirmation}
						required
						autocomplete="off"
					/></label
				>
			</PolarisForm>
		</div>
	</details>
</div>
