<script lang="ts">
	import {
		ChevronDown,
		LockKeyhole,
		Plus,
		Search,
		Shield,
		Trash2,
		UserRound,
		UsersRound
	} from '@lucide/svelte';
	import { untrack } from 'svelte';
	import type { PermissionGrant } from '$api/types';

	interface Props {
		grants: PermissionGrant[];
		scopeLabel: string;
		availableRoles?: PermissionGrant['role'][];
	}

	let {
		grants,
		scopeLabel,
		availableRoles = ['reader', 'developer', 'project_admin']
	}: Props = $props();
	let rows = $state(untrack(() => [...grants]));
	let dialog: HTMLDialogElement;
	let principalKind = $state<PermissionGrant['principalKind']>('user');
	let principal = $state('');
	let role = $state<PermissionGrant['role']>('reader');
	let filter = $state('');

	const roleNames: Record<PermissionGrant['role'], string> = {
		reader: 'Reader',
		developer: 'Developer',
		project_admin: 'Project admin',
		organization_admin: 'Organization admin',
		platform_owner: 'Platform owner'
	};

	const visibleRows = $derived(
		rows.filter((grant) =>
			`${grant.displayName} ${grant.principal} ${grant.role}`
				.toLowerCase()
				.includes(filter.toLowerCase())
		)
	);

	function iconFor(kind: PermissionGrant['principalKind']) {
		return kind === 'group' ? UsersRound : UserRound;
	}

	function addGrant() {
		const value = principal.trim();
		if (!value) return;
		rows = [
			...rows,
			{
				id: `grant-${Date.now()}`,
				principal: `${principalKind}:${value}`,
				displayName: value.includes('@') ? value.split('@')[0].replace(/[._-]/g, ' ') : value,
				principalKind,
				role,
				scope: scopeLabel,
				inherited: false
			}
		];
		principal = '';
		dialog.close();
	}
</script>

<div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
	<label class="relative block w-full sm:max-w-xs">
		<span class="visually-hidden">Filter permissions</span>
		<Search
			size={15}
			class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
		/>
		<input
			bind:value={filter}
			type="search"
			placeholder="Search users, teams, or roles"
			class="h-9 w-full rounded-md border border-app-line bg-app-bg pl-9 pr-3 text-sm outline-none focus:border-brand-strong"
		/>
	</label>
	<button
		type="button"
		onclick={() => dialog.showModal()}
		class="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
		><Plus size={16} /> Add permission</button
	>
</div>

<div class="overflow-hidden rounded-lg border border-app-line bg-app-card">
	<div
		class="hidden grid-cols-[minmax(220px,1fr)_190px_180px_44px] gap-3 border-b border-app-line bg-app-bg px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.09em] text-app-muted md:grid"
	>
		<span>User, team, or service account</span><span>Role</span><span>Granted at</span><span></span>
	</div>
	{#each visibleRows as grant (grant.id)}
		{@const Icon = iconFor(grant.principalKind)}
		<div
			class="grid gap-3 border-b border-app-line px-4 py-3 last:border-0 md:grid-cols-[minmax(220px,1fr)_190px_180px_44px] md:items-center"
		>
			<div class="flex min-w-0 items-center gap-3">
				<span
					class="grid size-9 shrink-0 place-items-center rounded-full border border-app-line bg-app-bg text-app-muted"
					><Icon size={16} /></span
				>
				<div class="min-w-0">
					<p class="truncate text-sm font-semibold capitalize">{grant.displayName}</p>
					<p class="truncate text-xs text-app-muted">{grant.principal}</p>
				</div>
			</div>
			<div>
				{#if grant.inherited}
					<div
						class="inline-flex items-center gap-1.5 rounded-md border border-app-line bg-app-bg px-2.5 py-1.5 text-xs font-medium text-app-muted"
					>
						<LockKeyhole size={13} />
						{roleNames[grant.role]}
					</div>
				{:else}
					<label class="relative block">
						<span class="visually-hidden">Role for {grant.displayName}</span>
						<select
							bind:value={grant.role}
							class="h-9 w-full appearance-none rounded-md border border-app-line bg-app-bg pl-2.5 pr-8 text-xs font-medium outline-none focus:border-brand-strong"
						>
							{#each availableRoles as option}<option value={option}>{roleNames[option]}</option
								>{/each}
						</select>
						<ChevronDown
							size={13}
							class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-app-muted"
						/>
					</label>
				{/if}
			</div>
			<div>
				{#if grant.inherited}
					<p class="text-xs font-medium">Inherited</p>
					<p class="text-[11px] text-app-muted">from {grant.inheritedFrom}</p>
				{:else}
					<p class="text-xs font-medium">
						This {scopeLabel.includes('/') ? 'project' : 'organization'}
					</p>
					<p class="truncate text-[11px] text-app-muted">{scopeLabel}</p>
				{/if}
			</div>
			<div class="flex justify-end">
				<button
					type="button"
					disabled={grant.inherited}
					onclick={() => (rows = rows.filter((row) => row.id !== grant.id))}
					class="grid size-8 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover hover:text-app-danger disabled:cursor-not-allowed disabled:opacity-30"
					aria-label={`Remove ${grant.displayName}`}><Trash2 size={15} /></button
				>
			</div>
		</div>
	{/each}
	{#if visibleRows.length === 0}<p class="px-4 py-10 text-center text-sm text-app-muted">
			No permissions match this filter.
		</p>{/if}
</div>

<div
	class="mt-4 flex items-start gap-2 rounded-md border border-app-line bg-app-bg p-3 text-xs text-app-muted"
>
	<Shield size={15} class="mt-0.5 shrink-0 text-brand-strong" />
	<span
		>Permissions inherit downward. Inherited grants must be changed at their source scope. A deny
		binding always wins.</span
	>
</div>

<dialog
	bind:this={dialog}
	class="m-auto w-[min(94vw,520px)] rounded-xl border border-app-line bg-app-raised p-0 text-app-fg shadow-[var(--shadow-popover)] backdrop:bg-black/40"
>
	<form
		method="dialog"
		onsubmit={(event) => {
			event.preventDefault();
			addGrant();
		}}
	>
		<div class="border-b border-app-line p-5">
			<h2 class="m-0 border-0 p-0 text-lg font-semibold">Add permission</h2>
			<p class="mt-1 text-sm text-app-muted">Grant a fixed Huron role at {scopeLabel}.</p>
		</div>
		<div class="grid gap-4 p-5">
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Principal type<select
					bind:value={principalKind}
					class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
					><option value="user">User</option><option value="group">Team / group</option></select
				></label
			>
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>{principalKind === 'user' ? 'Email or subject' : 'Group name'}<input
					bind:value={principal}
					required
					placeholder={principalKind === 'user' ? 'name@example.org' : 'science-data'}
					class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg outline-none focus:border-brand-strong"
				/></label
			>
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Role<select
					bind:value={role}
					class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
					>{#each availableRoles as option}<option value={option}>{roleNames[option]}</option
						>{/each}</select
				></label
			>
		</div>
		<div class="flex justify-end gap-2 border-t border-app-line p-4">
			<button
				type="button"
				onclick={() => dialog.close()}
				class="h-9 rounded-md border border-app-line px-3 text-sm font-semibold text-app-muted"
				>Cancel</button
			><button
				type="submit"
				class="h-9 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
				>Add permission</button
			>
		</div>
	</form>
</dialog>
