<script lang="ts">
	import {
		Building2,
		Check,
		KeyRound,
		LockKeyhole,
		Mail,
		MoreHorizontal,
		Plus,
		Search,
		ShieldCheck,
		UserRound,
		Users,
		Workflow,
		X
	} from '@lucide/svelte';
	import type { OrganizationMember, PermissionGrant } from '$api/types';
	import type { PageData } from './$types';
	import { untrack } from 'svelte';

	let { data }: { data: PageData } = $props();
	let active = $state<'general' | 'users' | 'service_accounts' | 'authentication'>('users');
	let members = $state(untrack(() => [...data.members]));
	let permissions = $state(untrack(() => [...data.permissions]));
	let inviteDialog: HTMLDialogElement;
	let serviceDialog: HTMLDialogElement;
	let inviteName = $state('');
	let inviteEmail = $state('');
	let inviteRole = $state<PermissionGrant['role']>('reader');
	let serviceName = $state('');
	let serviceRole = $state<PermissionGrant['role']>('pipeline');
	let userQuery = $state('');
	let serviceQuery = $state('');
	let saved = $state(false);

	const tabs = [
		{ id: 'general', label: 'General' },
		{ id: 'users', label: 'Users' },
		{ id: 'service_accounts', label: 'Service Accounts' },
		{ id: 'authentication', label: 'Authentication' }
	] as const;
	const userRoles: PermissionGrant['role'][] = [
		'reader',
		'developer',
		'data_steward',
		'project_admin',
		'organization_admin'
	];
	const serviceRoles: PermissionGrant['role'][] = ['pipeline', 'reader', 'developer'];
	const roleNames: Record<PermissionGrant['role'], string> = {
		reader: 'Reader',
		developer: 'Developer',
		data_steward: 'Data steward',
		project_admin: 'Project admin',
		organization_admin: 'Organization admin',
		platform_owner: 'Platform owner',
		pipeline: 'Pipeline'
	};

	interface PrincipalRow {
		id: string;
		displayName: string;
		principal: string;
		kind: OrganizationMember['kind'];
		status: OrganizationMember['status'];
		lastActiveAt: string | null;
		grant?: PermissionGrant;
	}

	function principalFor(member: OrganizationMember) {
		return member.kind === 'user' ? `user:${member.email}` : member.email;
	}

	function buildRows(kind: 'users' | 'service_accounts'): PrincipalRow[] {
		const includedKinds: OrganizationMember['kind'][] =
			kind === 'users' ? ['user', 'group'] : ['service_account'];
		const memberRows = members
			.filter((member) => includedKinds.includes(member.kind))
			.map((member) => {
				const principal = principalFor(member);
				return {
					...member,
					principal,
					grant: permissions.find((permission) => permission.principal === principal)
				};
			});
		const knownPrincipals = new Set(memberRows.map((row) => row.principal));
		const permissionOnlyRows = permissions
			.filter(
				(permission) =>
					includedKinds.includes(permission.principalKind) &&
					!knownPrincipals.has(permission.principal)
			)
			.map((permission) => ({
				id: `permission-${permission.id}`,
				displayName: permission.displayName,
				principal: permission.principal,
				kind: permission.principalKind,
				status: 'active' as const,
				lastActiveAt: null,
				grant: permission
			}));
		return [...memberRows, ...permissionOnlyRows];
	}

	const userRows = $derived(buildRows('users'));
	const serviceRows = $derived(buildRows('service_accounts'));
	const filteredUserRows = $derived(
		userRows.filter((row) =>
			`${row.displayName} ${row.principal} ${row.grant?.role ?? ''}`
				.toLowerCase()
				.includes(userQuery.toLowerCase())
		)
	);
	const filteredServiceRows = $derived(
		serviceRows.filter((row) =>
			`${row.displayName} ${row.principal} ${row.grant?.role ?? ''}`
				.toLowerCase()
				.includes(serviceQuery.toLowerCase())
		)
	);

	function invite() {
		if (!inviteEmail.trim()) return;
		const member: OrganizationMember = {
			id: `member-${Date.now()}`,
			displayName: inviteName.trim() || inviteEmail.split('@')[0],
			email: inviteEmail.trim(),
			kind: 'user',
			status: 'invited',
			lastActiveAt: null
		};
		members = [...members, member];
		permissions = [
			...permissions,
			{
				id: `grant-${member.id}`,
				principal: principalFor(member),
				displayName: member.displayName,
				principalKind: 'user',
				role: inviteRole,
				scope: data.organization.slug,
				inherited: false
			}
		];
		inviteName = '';
		inviteEmail = '';
		inviteRole = 'reader';
		inviteDialog.close();
	}

	function createServiceAccount() {
		const displayName = serviceName.trim();
		if (!displayName) return;
		const slug = displayName
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-|-$/g, '');
		const member: OrganizationMember = {
			id: `service-${Date.now()}`,
			displayName,
			email: `sa:${slug}`,
			kind: 'service_account',
			status: 'active',
			lastActiveAt: null
		};
		members = [...members, member];
		permissions = [
			...permissions,
			{
				id: `grant-${member.id}`,
				principal: member.email,
				displayName,
				principalKind: 'service_account',
				role: serviceRole,
				scope: data.organization.slug,
				inherited: false
			}
		];
		serviceName = '';
		serviceRole = 'pipeline';
		serviceDialog.close();
	}

	function setRole(row: PrincipalRow, value: PermissionGrant['role'] | 'none') {
		if (row.grant?.inherited) return;
		if (value === 'none') {
			permissions = permissions.filter((permission) => permission.id !== row.grant?.id);
			return;
		}
		if (row.grant) {
			row.grant.role = value;
			return;
		}
		permissions = [
			...permissions,
			{
				id: `grant-${Date.now()}`,
				principal: row.principal,
				displayName: row.displayName,
				principalKind: row.kind,
				role: value,
				scope: data.organization.slug,
				inherited: false
			}
		];
	}

	function memberIcon(kind: OrganizationMember['kind']) {
		return kind === 'group' ? Users : kind === 'service_account' ? Workflow : UserRound;
	}

	function formattedActivity(value: string | null) {
		return value ? new Date(value).toLocaleDateString() : 'Never';
	}
</script>

<svelte:head><title>Organization settings · Huron</title></svelte:head>

<div class="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
	<div class="flex items-center gap-3">
		<span class="grid size-11 place-items-center rounded-lg bg-brand-soft text-brand-strong"
			><Building2 size={21} /></span
		>
		<div>
			<p class="text-xs font-medium text-app-muted">Example Organization</p>
			<h1>Organization settings</h1>
		</div>
	</div>
	{#if active === 'users'}<button
			type="button"
			onclick={() => inviteDialog.showModal()}
			class="inline-flex h-9 items-center justify-center gap-2 self-start rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
			><Plus size={16} /> Add user</button
		>{/if}
	{#if active === 'service_accounts'}<button
			type="button"
			onclick={() => serviceDialog.showModal()}
			class="inline-flex h-9 items-center justify-center gap-2 self-start rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
			><Plus size={16} /> Create service account</button
		>{/if}
</div>

<nav
	class="mb-6 flex gap-1 overflow-x-auto border-b border-app-line"
	aria-label="Organization settings sections"
>
	{#each tabs as tab}
		<button
			type="button"
			onclick={() => (active = tab.id)}
			class="relative shrink-0 px-3 py-2.5 text-sm font-medium"
			class:text-brand-strong={active === tab.id}
			class:text-app-muted={active !== tab.id}
		>
			{tab.label}
			{#if active === tab.id}<span class="absolute inset-x-2 bottom-[-1px] h-0.5 bg-brand"
				></span>{/if}
		</button>
	{/each}
</nav>

{#if saved}
	<div
		class="mb-4 flex items-center gap-2 rounded-md border border-[var(--note-line)] bg-[var(--note-bg)] px-3 py-2.5 text-sm"
	>
		<Check size={16} class="text-app-success" /> Organization settings saved.<button
			type="button"
			onclick={() => (saved = false)}
			class="ml-auto"><X size={15} class="text-app-muted" /></button
		>
	</div>
{/if}

{#if active === 'general'}
	<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
		<section class="rounded-lg border border-app-line bg-app-card">
			<div class="border-b border-app-line p-5">
				<h2 class="m-0 border-0 p-0 text-base font-semibold">Organization profile</h2>
				<p class="mt-1 text-sm text-app-muted">Details visible across projects and the catalog.</p>
			</div>
			<div class="grid gap-4 p-5 sm:grid-cols-2">
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted sm:col-span-2"
					>Display name<input
						value={data.organization.name}
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
					/></label
				>
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Slug<input
						value={data.organization.slug}
						disabled
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 font-mono text-sm font-normal text-app-muted"
					/><span class="font-normal">Permanent after creation</span></label
				>
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Lifecycle<select
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
						><option>Active</option><option>Suspended</option></select
					></label
				>
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted sm:col-span-2"
					>Description<textarea
						rows="4"
						class="rounded-md border border-app-line bg-app-bg p-3 text-sm font-normal text-app-fg"
						>Scientific datasets and governed derived products for the Example Organization.</textarea
					></label
				>
			</div>
			<div class="flex justify-end border-t border-app-line p-4">
				<button
					type="button"
					onclick={() => (saved = true)}
					class="h-9 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
					>Save changes</button
				>
			</div>
		</section>
		<aside class="rounded-lg border border-app-line bg-app-card p-5">
			<h2 class="m-0 border-0 p-0 text-sm font-semibold">Organization details</h2>
			<dl class="mt-4 grid gap-3 text-xs">
				<div class="flex justify-between">
					<dt class="text-app-muted">Projects</dt>
					<dd class="font-semibold">{data.organization.projectCount}</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-app-muted">Users and teams</dt>
					<dd class="font-semibold">{userRows.length}</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-app-muted">Service accounts</dt>
					<dd class="font-semibold">{serviceRows.length}</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-app-muted">Created</dt>
					<dd class="font-semibold">Aug 16, 2026</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-app-muted">Region</dt>
					<dd class="font-semibold">us-west</dd>
				</div>
			</dl>
		</aside>
	</div>
{:else if active === 'users'}
	<section>
		<div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
			<label class="relative block w-full sm:max-w-xs">
				<span class="visually-hidden">Search users</span>
				<Search
					size={15}
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
				/>
				<input
					bind:value={userQuery}
					type="search"
					placeholder="Search users, teams, or roles"
					class="h-9 w-full rounded-md border border-app-line bg-app-card pl-9 pr-3 text-sm outline-none focus:border-brand-strong"
				/>
			</label>
			<div class="flex items-center gap-2 text-xs text-app-muted">
				<span class="size-2 rounded-full bg-app-success"></span>{userRows.filter(
					(row) => row.status === 'active'
				).length} active users and teams
			</div>
		</div>
		<div class="overflow-hidden rounded-lg border border-app-line bg-app-card">
			<div
				class="hidden grid-cols-[minmax(220px,1fr)_120px_180px_130px_44px] gap-3 border-b border-app-line bg-app-bg px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.09em] text-app-muted md:grid"
			>
				<span>User or team</span><span>Last active</span><span>Role</span><span>Granted at</span
				><span></span>
			</div>
			{#each filteredUserRows as row (row.id)}
				{@const Icon = memberIcon(row.kind)}
				<div
					class="grid gap-3 border-b border-app-line px-4 py-3 last:border-0 md:grid-cols-[minmax(220px,1fr)_120px_180px_130px_44px] md:items-center"
				>
					<div class="flex min-w-0 items-center gap-3">
						<span
							class="grid size-9 shrink-0 place-items-center rounded-full border border-app-line bg-app-bg text-app-muted"
							><Icon size={16} /></span
						>
						<div class="min-w-0">
							<div class="flex items-center gap-2">
								<p class="truncate text-sm font-semibold">{row.displayName}</p>
								{#if row.status === 'invited'}<span
										class="rounded-full bg-[var(--warn-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--accent2)]"
										>Invited</span
									>{/if}
							</div>
							<p class="truncate text-xs text-app-muted">{row.principal}</p>
						</div>
					</div>
					<p class="text-xs text-app-muted">{formattedActivity(row.lastActiveAt)}</p>
					{#if row.grant?.inherited}
						<div
							class="inline-flex w-fit items-center gap-1.5 rounded-md border border-app-line bg-app-bg px-2.5 py-1.5 text-xs font-medium text-app-muted"
						>
							<LockKeyhole size={13} />
							{roleNames[row.grant.role]}
						</div>
					{:else}
						<select
							value={row.grant?.role ?? 'none'}
							onchange={(event) =>
								setRole(row, event.currentTarget.value as PermissionGrant['role'] | 'none')}
							aria-label={`Role for ${row.displayName}`}
							class="h-9 w-full rounded-md border border-app-line bg-app-bg px-2.5 text-xs font-medium outline-none focus:border-brand-strong"
						>
							<option value="none">No role</option>
							{#each userRoles as role}<option value={role}>{roleNames[role]}</option>{/each}
						</select>
					{/if}
					<div>
						{#if row.grant?.inherited}
							<p class="text-xs font-medium">Inherited</p>
							<p class="text-[11px] text-app-muted">from {row.grant.inheritedFrom}</p>
						{:else if row.grant}
							<p class="text-xs font-medium">This organization</p>
							<p class="truncate text-[11px] text-app-muted">{data.organization.slug}</p>
						{:else}
							<p class="text-xs text-app-muted">Not granted</p>
						{/if}
					</div>
					<button
						type="button"
						class="grid size-8 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover"
						aria-label={`Actions for ${row.displayName}`}><MoreHorizontal size={16} /></button
					>
				</div>
			{/each}
			{#if filteredUserRows.length === 0}<p class="px-4 py-10 text-center text-sm text-app-muted">
					No users or teams match this search.
				</p>{/if}
		</div>
		<div
			class="mt-4 flex items-start gap-2 rounded-md border border-app-line bg-app-bg p-3 text-xs text-app-muted"
		>
			<ShieldCheck size={15} class="mt-0.5 shrink-0 text-brand-strong" />
			<span
				>Roles apply at this organization and inherit into its projects. Inherited roles must be
				changed at their source.</span
			>
		</div>
	</section>
{:else if active === 'service_accounts'}
	<section>
		<div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
			<label class="relative block w-full sm:max-w-xs">
				<span class="visually-hidden">Search service accounts</span>
				<Search
					size={15}
					class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-app-muted"
				/>
				<input
					bind:value={serviceQuery}
					type="search"
					placeholder="Search service accounts"
					class="h-9 w-full rounded-md border border-app-line bg-app-card pl-9 pr-3 text-sm outline-none focus:border-brand-strong"
				/>
			</label>
			<p class="text-xs text-app-muted">{serviceRows.length} machine identities</p>
		</div>
		<div class="overflow-hidden rounded-lg border border-app-line bg-app-card">
			<div
				class="hidden grid-cols-[minmax(240px,1fr)_120px_150px_180px_44px] gap-3 border-b border-app-line bg-app-bg px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.09em] text-app-muted md:grid"
			>
				<span>Service account</span><span>Status</span><span>Last active</span><span>Role</span
				><span></span>
			</div>
			{#each filteredServiceRows as row (row.id)}
				<div
					class="grid gap-3 border-b border-app-line px-4 py-3 last:border-0 md:grid-cols-[minmax(240px,1fr)_120px_150px_180px_44px] md:items-center"
				>
					<div class="flex min-w-0 items-center gap-3">
						<span
							class="grid size-9 shrink-0 place-items-center rounded-full border border-app-line bg-app-bg text-app-muted"
							><Workflow size={16} /></span
						>
						<div class="min-w-0">
							<p class="truncate text-sm font-semibold">{row.displayName}</p>
							<p class="truncate text-xs text-app-muted">{row.principal}</p>
						</div>
					</div>
					<p class="flex items-center gap-1.5 text-xs capitalize text-app-success">
						<span class="size-1.5 rounded-full bg-app-success"></span>{row.status}
					</p>
					<p class="text-xs text-app-muted">{formattedActivity(row.lastActiveAt)}</p>
					<select
						value={row.grant?.role ?? 'none'}
						onchange={(event) =>
							setRole(row, event.currentTarget.value as PermissionGrant['role'] | 'none')}
						aria-label={`Role for ${row.displayName}`}
						class="h-9 w-full rounded-md border border-app-line bg-app-bg px-2.5 text-xs font-medium outline-none focus:border-brand-strong"
					>
						<option value="none">No role</option>
						{#each serviceRoles as role}<option value={role}>{roleNames[role]}</option>{/each}
					</select>
					<button
						type="button"
						class="grid size-8 place-items-center rounded-md text-app-muted hover:bg-app-sidebar-hover"
						aria-label={`Actions for ${row.displayName}`}><MoreHorizontal size={16} /></button
					>
				</div>
			{/each}
			{#if filteredServiceRows.length === 0}<p
					class="px-4 py-10 text-center text-sm text-app-muted"
				>
					No service accounts match this search.
				</p>{/if}
		</div>
		<p class="mt-3 text-xs text-app-muted">
			Service accounts are non-human identities for automated jobs. Rotate their credentials and
			grant only the role each pipeline needs.
		</p>
	</section>
{:else}
	<div class="max-w-2xl">
		<section class="rounded-lg border border-app-line bg-app-card p-5">
			<div class="flex items-start gap-3">
				<span class="grid size-9 place-items-center rounded-md bg-brand-soft text-brand-strong"
					><KeyRound size={18} /></span
				>
				<div>
					<h2 class="m-0 border-0 p-0 text-base font-semibold">Identity provider</h2>
					<p class="mt-1 text-sm text-app-muted">OIDC session authentication for browser users.</p>
				</div>
			</div>
			<dl class="mt-5 grid gap-3 text-xs">
				<div class="flex justify-between border-b border-app-line pb-3">
					<dt class="text-app-muted">Provider</dt>
					<dd class="font-semibold">OpenShift OIDC</dd>
				</div>
				<div class="flex justify-between border-b border-app-line pb-3">
					<dt class="text-app-muted">Status</dt>
					<dd class="flex items-center gap-1.5 font-semibold text-app-success">
						<span class="size-1.5 rounded-full bg-app-success"></span>Connected
					</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-app-muted">Group sync</dt>
					<dd class="font-semibold">Every 15 minutes</dd>
				</div>
			</dl>
		</section>
	</div>
{/if}

<dialog
	bind:this={inviteDialog}
	class="m-auto w-[min(94vw,520px)] rounded-xl border border-app-line bg-app-raised p-0 text-app-fg shadow-[var(--shadow-popover)] backdrop:bg-black/40"
>
	<form
		method="dialog"
		onsubmit={(event) => {
			event.preventDefault();
			invite();
		}}
	>
		<div class="border-b border-app-line p-5">
			<div class="flex items-center justify-between">
				<h2 class="m-0 border-0 p-0 text-lg font-semibold">Add user</h2>
				<button type="button" onclick={() => inviteDialog.close()} aria-label="Close"
					><X size={18} class="text-app-muted" /></button
				>
			</div>
			<p class="mt-1 text-sm text-app-muted">
				Invite a user and choose their organization role in one step.
			</p>
		</div>
		<div class="grid gap-4 p-5">
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Display name<input
					bind:value={inviteName}
					placeholder="Maya Chen"
					class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
				/></label
			><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Email address<input
					bind:value={inviteEmail}
					required
					type="email"
					placeholder="maya@example.org"
					class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
				/></label
			><label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Organization role<select
					bind:value={inviteRole}
					class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
					>{#each userRoles as role}<option value={role}>{roleNames[role]}</option>{/each}</select
				></label
			><label
				class="flex items-start gap-2.5 rounded-md border border-app-line bg-app-bg p-3 text-xs text-app-muted"
				><input type="checkbox" checked class="mt-0.5 accent-[var(--brand-strong)]" /><span
					><strong class="block text-app-fg">Send an email invitation</strong>The member can sign in
					after their identity is resolved by OIDC.</span
				></label
			>
		</div>
		<div class="flex justify-end gap-2 border-t border-app-line p-4">
			<button
				type="button"
				onclick={() => inviteDialog.close()}
				class="h-9 rounded-md border border-app-line px-3 text-sm font-semibold text-app-muted"
				>Cancel</button
			><button
				type="submit"
				class="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
				><Mail size={15} /> Add user</button
			>
		</div>
	</form>
</dialog>

<dialog
	bind:this={serviceDialog}
	class="m-auto w-[min(94vw,520px)] rounded-xl border border-app-line bg-app-raised p-0 text-app-fg shadow-[var(--shadow-popover)] backdrop:bg-black/40"
>
	<form
		method="dialog"
		onsubmit={(event) => {
			event.preventDefault();
			createServiceAccount();
		}}
	>
		<div class="border-b border-app-line p-5">
			<div class="flex items-center justify-between">
				<h2 class="m-0 border-0 p-0 text-lg font-semibold">Create service account</h2>
				<button type="button" onclick={() => serviceDialog.close()} aria-label="Close"
					><X size={18} class="text-app-muted" /></button
				>
			</div>
			<p class="mt-1 text-sm text-app-muted">
				Create a machine identity with an organization-scoped role.
			</p>
		</div>
		<div class="grid gap-4 p-5">
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Display name<input
					bind:value={serviceName}
					required
					placeholder="Silver refresh pipeline"
					class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
				/></label
			>
			<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
				>Organization role<select
					bind:value={serviceRole}
					class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
					>{#each serviceRoles as role}<option value={role}>{roleNames[role]}</option
						>{/each}</select
				></label
			>
			<div class="rounded-md border border-app-line bg-app-bg p-3 text-xs text-app-muted">
				Credentials are shown once after creation. Store them in your organization secret manager.
			</div>
		</div>
		<div class="flex justify-end gap-2 border-t border-app-line p-4">
			<button
				type="button"
				onclick={() => serviceDialog.close()}
				class="h-9 rounded-md border border-app-line px-3 text-sm font-semibold text-app-muted"
				>Cancel</button
			><button
				type="submit"
				class="h-9 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
				>Create service account</button
			>
		</div>
	</form>
</dialog>
