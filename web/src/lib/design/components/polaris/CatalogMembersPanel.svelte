<script lang="ts">
	import type { HuronCatalogMember } from '$api/types';
	import PolarisForm from './PolarisForm.svelte';
	let { catalog, members }: { catalog: string; members: HuronCatalogMember[] } = $props();
	let query = $state('');
	const filtered = $derived(
		members.filter((member) =>
			`${member.user.username} ${member.user.displayName}`
				.toLowerCase()
				.includes(query.toLowerCase())
		)
	);
</script>

<section class="panel">
	<h2>Catalog users</h2>
	<p class="hint mb-4">
		Add Huron users to {catalog}. Membership and data privileges are persisted as Polaris
		principal-role → catalog-role grants.
	</p>
	<label class="mb-5"
		>Find a user<input type="search" bind:value={query} placeholder="Username or name" /></label
	>
	<div class="grid gap-4">
		{#each filtered as member (member.user.id)}
			<div class="rounded-md border border-app-line p-4">
				<div class="mb-3 flex flex-wrap items-center justify-between gap-2">
					<div>
						<h3 class="m-0 text-sm font-semibold">{member.user.displayName}</h3>
						<p class="hint">
							{member.user.username}{member.user.disabled ? ' · Disabled' : ''}{member.user.isAdmin
								? ' · Huron administrator'
								: ''}
						</p>
					</div>
					<span class="text-xs text-app-muted"
						>{member.roles.length
							? member.roles
									.map((role) =>
										role === 'admin' ? 'Catalog admin' : role === 'writer' ? 'Writer' : 'Reader'
									)
									.join(', ')
							: 'No managed catalog access'}</span
					>
				</div>
				{#if member.user.isAdmin}<p class="hint">
						The default administrator retains catalog access.
					</p>
				{:else}
					<PolarisForm action="setMembership" submit={`Save access for ${member.user.username}`}>
						<input type="hidden" name="catalog" value={catalog} />
						<input type="hidden" name="userId" value={member.user.id} />
						<label
							>Catalog role<select
								name="role"
								value={member.roles.includes('admin')
									? 'admin'
									: member.roles.includes('writer')
										? 'writer'
										: member.roles.includes('reader')
											? 'reader'
											: 'none'}
							>
								<option value="none">Remove managed access</option><option
									value="reader"
									disabled={member.user.disabled}>Reader</option
								><option value="writer" disabled={member.user.disabled}>Writer</option><option
									value="admin"
									disabled={member.user.disabled}>Catalog admin</option
								>
							</select></label
						>
					</PolarisForm>
				{/if}
			</div>
		{:else}<p class="hint">
				No matching Huron users. A Huron administrator can create users from Administration.
			</p>{/each}
	</div>
	<p class="notice">
		Reader can discover and read repositories. Writer can also create namespaces,
		register/unregister repositories and request write access. Catalog admin manages metadata,
		content and grants in this catalog; global principals and new catalogs require a Huron
		administrator. Advanced grants remain effective when managed access is removed.
	</p>
</section>
