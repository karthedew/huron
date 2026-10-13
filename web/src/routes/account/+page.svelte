<script lang="ts">
	import { resolve } from '$app/paths';
	import { UserRound } from '@lucide/svelte';
	import PolarisForm from '$design/components/polaris/PolarisForm.svelte';
	import '$design/polaris.css';
	import type { PageData, ActionData } from './$types';
	let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<svelte:head><title>Account · Huron</title></svelte:head>

<div class="polaris-workspace min-w-0">
	<div class="mb-6">
		<p class="mb-2 flex items-center gap-2 text-xs font-semibold text-app-muted">
			<UserRound size={15} /> Your Huron login
		</p>
		<h1>Account</h1>
	</div>
	{#if form}<p class="mb-5 rounded-md border border-app-danger/40 p-3 text-sm" role="alert">
			{form.message}
		</p>{/if}
	<div class="grid gap-5 xl:grid-cols-2">
		<section class="panel">
			<h2>Identity</h2>
			<dl class="property-list mt-4">
				<div>
					<dt>Username</dt>
					<dd>{data.account?.username}</dd>
				</div>
				<div>
					<dt>Name</dt>
					<dd>{data.account?.displayName}</dd>
				</div>
				<div>
					<dt>Polaris principal</dt>
					<dd>{data.account?.polarisPrincipal}</dd>
				</div>
				<div>
					<dt>Account role</dt>
					<dd>{data.account?.isAdmin ? 'Huron administrator' : 'Huron user'}</dd>
				</div>
			</dl>
			<h3 class="mb-3 text-sm font-semibold">Visible Polaris catalogs</h3>
			<ul class="grid gap-2">
				{#each data.catalogs as catalog (catalog.name)}<li>
						<a
							href={resolve(`/browse?catalog=${encodeURIComponent(catalog.name)}`)}
							class="resource-link">{catalog.name}</a
						>
					</li>{:else}<li class="hint">
						No catalog access yet. Ask a catalog administrator to add your user.
					</li>{/each}
			</ul>
			<p class="notice">
				Polaris authorizes each request using your own principal. Catalog users and advanced Polaris
				grants determine what you can discover, read and change.
			</p>
		</section>
		<section class="panel self-start">
			<h2>Change password</h2>
			<p class="hint mb-4">
				A successful change ends your current Huron sessions. Sign in again with the new password.
			</p>
			<PolarisForm action="changePassword" submit="Change password"
				><label
					>Current password<input
						name="currentPassword"
						type="password"
						required
						autocomplete="current-password"
					/></label
				><label
					>New password<input
						name="newPassword"
						type="password"
						minlength="12"
						required
						autocomplete="new-password"
					/></label
				></PolarisForm
			>
		</section>
	</div>
</div>
