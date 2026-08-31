<script lang="ts">
	import {
		Activity,
		ArrowRight,
		Building2,
		CheckCircle2,
		ClipboardList,
		FolderCog,
		Gauge,
		RefreshCw,
		ShieldCheck,
		Users,
		Workflow
	} from '@lucide/svelte';

	const audit = [
		{
			actor: 'Karl Schmidt',
			action: 'granted developer',
			target: 'group:science-data',
			age: '12 min ago'
		},
		{
			actor: 'Bronze Pipeline',
			action: 'committed snapshot',
			target: 'example-sweep/run-0002',
			age: '38 min ago'
		},
		{
			actor: 'Maya Chen',
			action: 'updated retention policy',
			target: 'example-study',
			age: '2 hr ago'
		}
	];
</script>

<svelte:head><title>Administration · Huron</title></svelte:head>

<div class="mb-7">
	<div
		class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.11em] text-app-muted"
	>
		<ShieldCheck size={14} /> Governance
	</div>
	<h1>Administration</h1>
	<p class="mt-2 max-w-2xl text-sm text-app-muted">
		Organization-scoped governance, role bindings, audit activity, and platform health.
	</p>
</div>

<div class="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
	<div class="rounded-lg border border-app-line bg-app-card p-4">
		<div class="flex items-center justify-between">
			<span class="text-xs font-medium text-app-muted">Active members</span><Users
				size={16}
				class="text-brand-strong"
			/>
		</div>
		<p class="mt-2 text-2xl font-semibold">4</p>
		<p class="mt-1 text-xs text-app-muted">1 service account</p>
	</div>
	<div class="rounded-lg border border-app-line bg-app-card p-4">
		<div class="flex items-center justify-between">
			<span class="text-xs font-medium text-app-muted">Effective bindings</span><ShieldCheck
				size={16}
				class="text-brand-strong"
			/>
		</div>
		<p class="mt-2 text-2xl font-semibold">7</p>
		<p class="mt-1 text-xs text-app-muted">3 inherited</p>
	</div>
	<div class="rounded-lg border border-app-line bg-app-card p-4">
		<div class="flex items-center justify-between">
			<span class="text-xs font-medium text-app-muted">Open jobs</span><Workflow
				size={16}
				class="text-app-muted"
			/>
		</div>
		<p class="mt-2 text-2xl font-semibold">2</p>
		<p class="mt-1 text-xs text-app-muted">Bronze materialization</p>
	</div>
	<div class="rounded-lg border border-app-line bg-app-card p-4">
		<div class="flex items-center justify-between">
			<span class="text-xs font-medium text-app-muted">Platform health</span><CheckCircle2
				size={16}
				class="text-app-success"
			/>
		</div>
		<p class="mt-2 text-2xl font-semibold">Healthy</p>
		<p class="mt-1 text-xs text-app-muted">All stores reachable</p>
	</div>
</div>

<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
	<section class="rounded-lg border border-app-line bg-app-card">
		<div class="flex items-center justify-between border-b border-app-line p-5">
			<div>
				<h2 class="m-0 border-0 p-0 text-base font-semibold">Administration areas</h2>
				<p class="mt-1 text-sm text-app-muted">
					Manage within the authority of your own role bindings.
				</p>
			</div>
			<Gauge size={18} class="text-app-muted" />
		</div>
		<div class="grid gap-3 p-4 sm:grid-cols-2">
			<a
				href="/settings/organization"
				class="group rounded-lg border border-app-line p-4 hover:border-brand-strong"
				><span class="grid size-9 place-items-center rounded-md bg-brand-soft text-brand-strong"
					><Building2 size={18} /></span
				>
				<div class="mt-4 flex items-center justify-between">
					<h3 class="m-0 text-sm font-semibold">Organization</h3>
					<ArrowRight size={15} class="text-app-muted group-hover:text-brand-strong" />
				</div>
				<p class="mt-1 text-xs leading-5 text-app-muted">
					Members, roles, service accounts, and authentication.
				</p></a
			>
			<a
				href="/settings/project"
				class="group rounded-lg border border-app-line p-4 hover:border-brand-strong"
				><span class="grid size-9 place-items-center rounded-md bg-brand-soft text-brand-strong"
					><FolderCog size={18} /></span
				>
				<div class="mt-4 flex items-center justify-between">
					<h3 class="m-0 text-sm font-semibold">Projects</h3>
					<ArrowRight size={15} class="text-app-muted group-hover:text-brand-strong" />
				</div>
				<p class="mt-1 text-xs leading-5 text-app-muted">
					Access, classifications, quotas, and retention policies.
				</p></a
			>
			<a href="/queue" class="group rounded-lg border border-app-line p-4 hover:border-brand-strong"
				><span class="grid size-9 place-items-center rounded-md bg-brand-soft text-brand-strong"
					><Activity size={18} /></span
				>
				<div class="mt-4 flex items-center justify-between">
					<h3 class="m-0 text-sm font-semibold">Jobs & queue</h3>
					<ArrowRight size={15} class="text-app-muted group-hover:text-brand-strong" />
				</div>
				<p class="mt-1 text-xs leading-5 text-app-muted">
					Ingest sessions, projections, and layer pipelines.
				</p></a
			>
			<a href="/admin" class="group rounded-lg border border-app-line p-4 hover:border-brand-strong"
				><span class="grid size-9 place-items-center rounded-md bg-brand-soft text-brand-strong"
					><RefreshCw size={18} /></span
				>
				<div class="mt-4 flex items-center justify-between">
					<h3 class="m-0 text-sm font-semibold">Reconciliation</h3>
					<span class="rounded-full bg-app-bg px-2 py-0.5 text-[10px] text-app-muted">Soon</span>
				</div>
				<p class="mt-1 text-xs leading-5 text-app-muted">
					Dry-run plans and degraded resource findings.
				</p></a
			>
		</div>
	</section>

	<section class="rounded-lg border border-app-line bg-app-card">
		<div class="flex items-center justify-between border-b border-app-line p-5">
			<div>
				<h2 class="m-0 border-0 p-0 text-base font-semibold">Recent audit activity</h2>
				<p class="mt-1 text-sm text-app-muted">Append-only organization events.</p>
			</div>
			<ClipboardList size={18} class="text-app-muted" />
		</div>
		<div class="divide-y divide-app-line">
			{#each audit as event}<div class="p-4">
					<p class="text-sm">
						<strong>{event.actor}</strong> <span class="text-app-muted">{event.action}</span>
					</p>
					<p class="mt-1 truncate font-mono text-[11px] text-brand-strong">{event.target}</p>
					<p class="mt-1 text-[11px] text-app-muted">{event.age}</p>
				</div>{/each}
		</div>
		<div class="border-t border-app-line p-3 text-center">
			<button type="button" class="text-xs font-semibold text-brand-strong"
				>Open full audit stream</button
			>
		</div>
	</section>
</div>
