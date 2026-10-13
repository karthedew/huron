<script lang="ts">
	import type { PolarisCatalog } from '$api/types';
	import PolarisForm from './PolarisForm.svelte';
	let { catalog, allowDrop = false }: { catalog: PolarisCatalog; allowDrop?: boolean } = $props();
	let confirmation = $state('');
</script>

<section class="panel">
	<h2>Catalog configuration</h2>
	<p class="hint mb-4">
		{catalog.name} is the Polaris catalog represented as an organization in Huron.
	</p>
	<PolarisForm action="updateCatalog" submit="Save catalog configuration">
		<input type="hidden" name="catalog" value={catalog.name} />
		<input type="hidden" name="currentEntityVersion" value={catalog.entityVersion ?? ''} />
		<label
			>Default repository base URI<input
				name="defaultBaseLocation"
				value={catalog.properties['default-base-location'] ?? ''}
				required
			/></label
		>
		<label
			>Catalog properties · JSON<textarea
				name="properties"
				rows="5"
				value={JSON.stringify(catalog.properties, null, 2)}
			></textarea></label
		>
		<label
			>Storage configuration · JSON<textarea
				name="storageConfigInfo"
				rows="6"
				value={JSON.stringify(catalog.storageConfigInfo, null, 2)}
			></textarea></label
		>
		<p class="hint">
			Storage configuration supports FILE, S3, GCS and AZURE. Use the provider’s Polaris
			configuration fields; Huron sends this configuration to the configured Polaris endpoint.
		</p>
	</PolarisForm>
	{#if catalog.storageConfigInfo.storageType === 'FILE'}<p class="notice">
			FILE storage does not vend cloud credentials. Direct Icechunk SDK access requires filesystem
			access to this repository space.
		</p>{/if}
	{#if allowDrop}
		<details class="editor">
			<summary class="text-app-danger">Drop catalog</summary>
			<PolarisForm
				action="deleteCatalog"
				submit="Drop catalog"
				danger
				disabled={confirmation !== catalog.name}
			>
				<input type="hidden" name="catalog" value={catalog.name} />
				<p class="hint">
					Remove repositories and namespaces first. Dropping an empty catalog also removes its
					catalog roles and grants. Repository files and Icechunk history remain in storage.
				</p>
				<label
					>Type {catalog.name} to confirm<input
						name="confirmation"
						bind:value={confirmation}
						required
						autocomplete="off"
					/></label
				>
			</PolarisForm>
		</details>
	{/if}
</section>
