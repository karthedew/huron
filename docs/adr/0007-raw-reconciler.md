---
status: accepted
---

# The reconciler is a server CronJob with mark-and-sweep findings

The volume-versus-catalog reconciler runs as a nightly CronJob from the API image under the pods'
service identity (L-15 (b)). No human token can start it, and no route or CLI flag can either: the spec's
`huron check --repair` is dropped (OQ-16.2 (a)). On demand, an operator runs
`kubectl create job --from=cronjob/huron-reconcile`. The reconciler repairs only what is idempotent and
touches no user-named bytes: stale partials, `metadata.json`, empty orphan directories, staged moves
and directory ACLs. Everything else becomes a finding. A finding stays open until a run repairs it or a
finished run of its catalog no longer sees it (the sweep). A failed or partial walk never clears what it
could not see. `huron check` reads the findings at Project Admin (OQ-16.1 (a)). We chose this over
per-code "is it fixed?" probes, which would need fourteen bespoke checks, and over a CLI-driven repair,
which would need a non-human credential that is out of scope.
