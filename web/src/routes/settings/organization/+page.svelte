<script lang="ts">
	import { Building2, Database, Users } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import PolarisForm from '$design/components/polaris/PolarisForm.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import '$design/polaris.css';
	import type { PageData, ActionData } from './$types';
	let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Organization settings · Huron</title></svelte:head>
<div class="polaris-workspace min-w-0">
	<div class="mb-6">
		<p class="mb-2 flex items-center gap-2 text-xs font-semibold text-app-muted">
			<Building2 size={15} /> Organization
		</p>
		<h1>{data.organization?.name ?? 'Organization settings'}</h1>
		<p class="mt-2 text-sm text-app-muted">
			Manage membership and the catalogs owned by this organization.
		</p>
	</div>
	{#if form}<p
			role={form.success ? 'status' : 'alert'}
			class={[
				'mb-5 rounded-md border p-3 text-sm',
				form.success
					? 'border-app-success/40 bg-brand-soft'
					: 'border-app-danger/40 bg-app-danger/10'
			]}
		>
			{form.message}
		</p>{/if}
	{#if data.organization}
		<div class="grid gap-5 xl:grid-cols-2">
			<section class="panel self-start">
				<h2>Organization details</h2>
				<p class="hint mb-4">Polaris realm: {data.organization.realm}</p>
				{#if data.canManage}<PolarisForm action="updateOrganization" submit="Save organization"
						><input type="hidden" name="organization" value={data.organization.slug} /><label
							>Organization name<input name="name" value={data.organization.name} required /></label
						><label
							>Description<textarea
								name="description"
								rows="3"
								value={data.organization.description}
							></textarea></label
						>
						<p class="hint">Stable identifier: {data.organization.slug}</p></PolarisForm
					>
				{:else}<p class="mt-3 text-sm text-app-muted">
						{data.organization.description || 'No description provided.'}
					</p>
					<p class="hint mt-3">
						Your organization role: Member. An organization administrator can update membership and
						settings.
					</p>{/if}
			</section>
			<section class="panel self-start">
				<h2 class="flex items-center gap-2"><Database size={17} /> Catalogs</h2>
				<p class="hint mb-4">
					Each catalog has its own storage and Polaris access rules. Dataset types can share a
					catalog.
				</p>
				<div class="grid gap-3">
					{#each data.catalogs as catalog (catalog.name)}<div
							class="flex flex-wrap items-center justify-between gap-3 rounded-md border border-app-line p-3"
						>
							<a
								class="min-w-0 break-all text-sm font-semibold"
								href={resolve(
									`/browse?catalog=${encodeURIComponent(catalog.name)}&organization=${encodeURIComponent(data.organization.slug)}`
								)}>{catalog.name}</a
							><a
								class="text-xs"
								href={resolve(
									`/settings/catalog?catalog=${encodeURIComponent(catalog.name)}&organization=${encodeURIComponent(data.organization.slug)}`
								)}>Catalog settings</a
							>
						</div>{:else}<p class="hint">No accessible catalogs in this organization.</p>{/each}
				</div>
				{#if data.user?.isAdmin}<a
						class="mt-4 inline-block text-sm"
						href={resolve(
							`/admin?tab=catalogs&organization=${encodeURIComponent(data.organization.slug)}`
						)}>Create catalogs</a
					>{/if}
			</section>
			{#if data.canManage}<section class="panel xl:col-span-2">
					<h2 class="flex items-center gap-2"><Users size={17} /> Organization members</h2>
					<p class="hint mb-4">
						Organization membership provides workspace access. Dataset access still requires a
						catalog role in Polaris. Remove catalog grants before removing an organization member.
					</p>
					<div class="mb-6 grid gap-3">
						{#each data.members as member (member.user.id)}<div
								class="min-w-0 rounded-md border border-app-line p-4"
							>
								<h3 class="m-0 break-words text-sm font-semibold">{member.user.displayName}</h3>
								<p class="hint mb-3">
									{member.user.username} · {member.user.isAdmin
										? 'Huron administrator'
										: member.role === 'admin'
											? 'Organization administrator'
											: 'Member'}
								</p>
								{#if !member.user.isAdmin}<PolarisForm
										action="setOrganizationMembership"
										submit={`Save organization role for ${member.user.username}`}
										><input
											type="hidden"
											name="organization"
											value={data.organization.slug}
										/><input type="hidden" name="username" value={member.user.username} /><label
											>Organization role for {member.user.username}<select
												name="role"
												value={member.role}
												><option value="member">Member</option><option value="admin"
													>Organization administrator</option
												><option value="none">Remove membership</option></select
											></label
										></PolarisForm
									>{/if}
							</div>{/each}
					</div>
					<h3>Add an existing Huron user</h3>
					<PolarisForm action="setOrganizationMembership" submit="Add organization member"
						><input type="hidden" name="organization" value={data.organization.slug} /><label
							>Username<input name="username" required autocomplete="off" /></label
						><label
							>Organization role<select name="role"
								><option value="member">Member</option><option value="admin"
									>Organization administrator</option
								></select
							></label
						>
						<p class="hint">
							Use their existing username. Adding a member does not grant access to any catalog.
						</p></PolarisForm
					>
				</section>{/if}
		</div>
	{:else}<EmptyState
			title="No organization available"
			detail="A Huron administrator can create an organization and add your account."
		/>{/if}
</div>
