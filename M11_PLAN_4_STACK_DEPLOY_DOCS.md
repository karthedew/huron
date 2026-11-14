# M11 plan 4: CLI verbs, check, stacks, deployment and documentation

Read [M11_PLANS.md](M11_PLANS.md) first. This plan delivers the old tasks M11.8 to M11.13.

## How to read this plan

Each task below points to a task in `IMPLEMENTATION_PLAN.md`. The text of that old task binds:
its "Create or change" list, its tests and its "Verification" entry. This plan lists only the
changes to that text. Read the old task in full before the work.

M11.6 "Removals, the background runner and the sweep" has no task here. Plan 2 replaces it:
a removal is a step of a commit, and cleanup selects by database ID. Do not build `Unlinker`,
`Sweeper`, the removal lease or a sweep by modification time.

## Tasks

### D1 Share group and `adm repair` in the CLI (old M11.8)

- Changes to the old task:
  - A busy collection (409 `COLLECTION_BUSY`) gets a hint that names `huron status`.
  - No ACL reminder in any message.
- Verification: the old task's entry, and the web gate when `web/src/lib/cli.ts` changes.
- Dependencies: plans 1 to 3.
- Status: complete (verification 3 of 3 passed, 2026-11-12). Verifications 1 and 2 failed on small
  findings in the tests and the help text. Coverage: 11680 statements with 2 missed before,
  11755 with 0 missed after. `web/src/lib/cli.ts` did not change, so the web gate did not run.
  For D2: `docs/concepts/raw-ingest.md` and `docs/concepts/access-and-roles.md` still say that
  the CLI has no `adm provision-catalogs`.

### D2 The check and provisioning (old M11.9)

- Changes to the old task:
  - `huron adm check` reports a pending commit as information, not as drift. During a pending
    commit a directory can hold a mix of old and new files.
  - The check reports these entries and never removes them: a temporary name of a publication, a
    `.nfs*` file, a `.snapshot` directory, a file that no row names.
  - Provisioning also prepares `<root>/<org>/.huron-objects/` (mode 0700, service UID) for each
    organization, and `.tus-uploads`.
  - `huron adm check` skips `.huron-objects`. It is a reserved name, not drift.
  - `huron adm check` reports a `.huron-link-probe-*` file that is older than one hour, in an
    organization directory or its object area. A killed readiness probe can leave one. The
    check does not remove it.
  - Provisioning must work with the API stopped. It reads its input from a file and makes no
    API request in that mode.
- Verification: the old task's entry.
- Dependencies: D1.
- Status: complete (verification 8 passed, 2026-11-12). Verifications 1 to 7 failed on small
  findings, and the owner authorized each cycle after the third. The gate at the last
  verification: 4487 tests passed, 24 deselected, 0 skipped; 12332 statements, 0 missed; 68
  clones in 25 groups against the baseline of 69 in 25. See "Escalation (D2, 2026-11-12)" for
  the verification reports and the owner decisions. That section is a record: the escalation
  is closed.

### D3 Development stacks and the integration tier (old M11.10)

- Changes to the old task:
  - Images: `tusproject/tusd:v2.10.1` and `nginx:1.31.8`, with `--pull=never`.
  - The tusd flags and the nginx block are those of "Recommended tusd flags" and "Recommended
    nginx configuration" in the S1 results of plan 2.
  - A step removes the stale `*.lock` files in `.tus-uploads` before tusd starts. This is safe
    only with one tusd, after the old one is gone. The stack must not start a second tusd.
  - Tests through nginx: a chunk of 64 MiB passes, and a `PATCH` of 2 MiB passes the
    authorization location.
  - `scripts/dev-login.sh` stays as it is.
  - The integration tests cover: new, overwrite, remove, empty file, resume after an interrupted
    `PATCH`, a final `PATCH` with no answer, a late completion after a newer commit, a token of
    another user on `HEAD` and `PATCH`.
  - Remove the skip of `tests/integration/test_cli_end_to_end.py`.
  - The NOAA demo runs two times on the same stack. The second run makes no upload and no commit.
- Verification: the old task's entry, `uv run pytest -m integration`, `scripts/e2e.sh`,
  `make demo-noaa` two times.
- Dependencies: D2.
- Status: complete (verification 5 passed, 2026-11-12). Verifications 1 to 4 failed. The owner
  raised the limit to 10 verifications after the third. The runs at the last verification:
  `make gate` with 4515 tests passed, 39 deselected, 0 skipped, 12332 statements, 0 missed and
  68 clones in 25 groups against the baseline of 69 in 25; `uv run pytest -m integration` with
  39 passed; the web gate; `scripts/e2e.sh`; `make demo-noaa` two times on a private stack,
  where the second run made no upload and no commit. `make app` and `make up` were not run
  with their default project names: their parts ran in private projects. See "Escalation (D3,
  2026-11-12)" for the verification reports, the owner decisions, a defect for a later task
  and an open question for the owner. The record of the fix passes follows. Verification 4
  failed on one documentation finding: the two
  development stacks share one lake and keep separate databases, and no document said so.
  - Fix pass 5, text only:
    - `README.md` has a section "One lake, two databases". It says that the catalog directories
      of one stack stop the seed, the demo or a create of the same catalog on the other stack
      with `STORAGE_FAILED`. It gives the two ways before a change: delete the directories as in
      step 2 of the reset procedure, or give one stack a lake of its own, with the variables for
      `make app`, `make api`, `make uploads` and `make demo-noaa`. It also says that a token of
      one stack is not valid on the other. The Quick start, the reset procedure,
      `web/README.md` and `examples/noaa/README.md` link to it.
    - The custom-lake paragraph of `README.md` says that each later `make app` needs the three
      variables again, that `make demo-noaa` needs `HURON_LAKE_PATH`, and that the variables must
      not be exported.
    - The repair command of `examples/noaa/README.md` uses `$HOME` in place of `~`.
    - An interaction review asked, for each ordered pair of the development commands, the
      custom lake, `scripts/e2e.sh`, the web e2e tests and the integration tier, whether the
      second still works as the documents say after the first. It looked at the shared lake and
      its markers, `.tus-uploads`, the two database volumes, the ports, the CLI configuration and
      tokens, the image tags and the owner of the files. It used the Makefile, the compose files,
      the scripts and the code, and ran no stack.
  - `make gate` after fix pass 5 exits 0: 4515 passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
  - Earlier: verification 3 failed on one documentation finding in `README.md`: four places said
    to run `make app-reset` and then `make app` with no step between them. The owner raised the
    limit to 10 verifications for each D task on 2026-11-12.
  - Fix pass 4, text only:
    - `README.md` has one procedure, "Start again with an empty database": `make app-reset`,
      delete the catalog directories in the three organization directories and keep `.huron`
      and `.huron-objects`, then `make app`. The four places give it or link to it. It also says
      what to do when `make app` already failed in that way.
    - `examples/noaa/README.md` links to the procedure. It also tells how to continue after a
      load stopped and its catalog directory was deleted: `huron adm repair planetary
      --recursive` with the CLI of the demo, then `make demo-noaa` again. A run on a private
      stack confirmed the error and this recovery.
    - `docs/architecture.md` gives port 1080 for each stack: `make app` publishes it on
      127.0.0.1, and nginx of `make uploads` listens on each interface.
    - A sweep by behaviour listed what D3 changed in the development workflow. It then read the
      stack parts of `README.md`, `web/README.md`, `examples/noaa/README.md`,
      `docs/architecture.md`, `docs/operator.md`, `AGENTS.md`, `CONTEXT.md`, the `Makefile`, the
      compose files, `huron.dev.yaml`, `dev.env`, `web/.env.example`, the headers of the scripts
      and `docker/seed/run.mjs`. It fixed more sentences that D3 made false. Examples: the API
      of `make api` does not start without `/data1/huron`, and `make app` and `make uploads`
      stop each other first. It did not read the other files of the repository.
  - `make gate` after fix pass 4 exits 0: 4515 passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
  - Earlier: fix pass 3 was done. Verification 2 failed on one documentation finding:
    `examples/noaa/README.md` said that `make app` takes no uploads and that `load.sh` reuses
    the directories of a load after `make app-reset`.
  - Fix pass 3, text only: `examples/noaa/README.md` now names the two stacks of
    `make demo-noaa`, its steps and the second run. After `make app-reset`, the load stops at
    the catalog directory that is not empty, so delete that directory and keep `.huron` and
    `.huron-objects`. `web/README.md` says that the seed with `make api` needs `make uploads`
    and a prepared lake. A sweep of the tracked text files found no other sentence that D3
    made false.
  - `make gate` after fix pass 3 exits 0: 4515 passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
  - Earlier: verification 1 failed on three findings:
    - F1: no integration test of an overwrite beside a part file of an earlier attempt.
    - F2: the seed of `make app` did not send its files through the proxy and tusd.
    - F3: the containers of the upload stack leaked when the stack of the CLI test failed to
      start.
    - Fix pass 2:
      - F1: a new test pushes an overwrite of `a.txt` beside `.a.txt.<UUID>.huron-part`. The new
        bytes are published, and the part file keeps its bytes.
      - F2: `docker/seed/run.mjs` reads `uploads_url` and sends each file with tus (a creation,
        then `PATCH` requests of at most 64 MiB, the user's token on each). `seed.mjs` keeps the
        lake path for the web e2e stack, which has no tusd. The seed no longer mounts the lake,
        and it waits for the healthy proxy.
      - F3: `UploadStack.start` and the stack of the CLI test remove what they started when a
        step fails. Unit tests fake the container runtime at the `subprocess` boundary. A real
        failure (a held proxy port) left no container.
      - Also: tusd of `make app` starts after `lake-init`. The stale commit of the late-completion
        test must give `BASE_VERSION_CONFLICT`. The tests read the hook timeout from the compose
        file.
    - `make gate` exits 0: 4515 passed, 39 deselected, 0 skipped. 12332 statements, 0 missed. 68
      clones in 25 groups against the baseline of 69 in 25.
    - `uv run pytest -m integration`: 39 passed, 0 skipped, 119 s.
    - Web gate: `npm run check` 0 errors and 0 warnings, `npm test` 1649 passed, `npm run lint`
      and `npm run build` exit 0, `npm run test:e2e` 245 passed.
    - `scripts/e2e.sh`: exit 0 in 38 s. Both pushes went through the proxy and tusd
      ("version 2 → 3, +2 −0 files", then "version 3 → 4, +2 −1 files"), and it ended with
      "e2e: ok".
    - One private stack (project `huron-d3demo`, its own API image, a lake in a scratch
      directory, `HURON_DEV_CONFIG` with that lake as `lake_path` and as each root):
      - tusd started after `lake-init` ended. A second `docker compose up` ran `lake-init` again
        and did not restart tusd.
      - The seed: exit 0 in 9 s. The proxy answered 124 `POST /files/` with 201 and 124 `PATCH`
        with 204. All 124 attempts are consumed, and 3 commit requests succeeded.
      - `make demo-noaa` run 1: exit 0 in 53 s, six uploads and six commits.
      - `make demo-noaa` run 2: exit 0 in 30 s. Each collection printed "nothing to push" and
        "metadata unchanged". The commits (9), the upload attempts (130) and the requests to the
        proxy (130 `POST`, 130 `PATCH`) did not change. Each collection stayed at version 3.
    - Adaptations to plan 2, for the verifier to judge. A link in place of a namespace directory
      blocks the commit (202, state `blocked`, `PUBLICATION_BLOCKED` with the reason
      `symbolic_link`), because the pre-finish hook now only seals into the object area. A commit
      that names an upload that is not `ready` gets 409 `UPLOAD_INELIGIBLE`. This replaces the
      commit without a receipt.
    - Choices where the plan is silent or old. The lock step runs in the tusd container before
      `exec tusd`, not in a one-shot `uploads-init`: a second `docker compose up` starts a
      finished one-shot service again while tusd runs. The fixed forwarded host and scheme are two
      more template variables, `HURON_UPLOADS_HOST` and `HURON_UPLOADS_PROTO`. The integration
      tests have no skip without Docker: they fail.

### D4 Kustomize base and the local cluster (old M11.11)

- Changes to the old task:
  - One API replica with the `Recreate` strategy. The manifest test fails on a replica count
    other than 1.
  - One tusd, in the same pod or with the same `Recreate` rule. A step before tusd starts
    removes the stale `*.lock` files in `.tus-uploads`. The manifest test fails when this step
    is present and the replica count is not 1.
  - Readiness includes the hard-link probe of plan 2 for each organization directory.
  - `terminationGracePeriodSeconds` is longer than the longest seal that the settings allow.
  - Readiness: probe timeout 3 s, period 5 s, failure threshold 3. Liveness does no NFS call.
  - The smoke test logs in on the host only. It copies no token into a pod. It runs
    `huron adm check --hash` from the host mount.
- Open item: `kubectl` is on this workstation. A local cluster tool is not. The owner supplies a
  cluster context before this task starts.
- Verification: the old task's entry.
- Dependencies: D3.
- Status: complete (2026-11-13). Verification 9 passed after 9 implementation passes; verifications
  1 to 8 failed. The owner decided on 2026-11-13 that the cluster of this task is the kind cluster
  `huron-local` with ingress-nginx on 127.0.0.1:18444, not `ocp-test`. The node of `ocp-test`
  shows no directory of the host, and `ocp-test` holds port 18443. `ocp-test` stays read-only.
  - Done: the base `deploy/openshift` (the API with one replica, `Recreate`, the lake claim, the
    service user and group, the probes and a grace period of 90 s; `uploads.yaml` with the upload
    pod, its Service, its Route and the claim `huron-lake`), the overlay `deploy/local` with
    `kind.yaml.template`, `scripts/k8s-local.sh` with the targets `k8s-local-cluster`,
    `k8s-local`, `k8s-local-smoke` and `k8s-local-down`, `tests/unit/test_deploy_manifests.py`,
    a liveness test in `tests/unit/api/test_service.py`, `deploy/README.md`, and the deployment
    text of `docs/operator.md` and `docs/architecture.md`. The readiness probe of plan 2 was in
    the code already. The manifests now use it.
  - The script gives `K8S_LOCAL_KUBECONFIG` (default `~/.kube/huron-local.config`) to each
    kubectl and kind command, with the context `kind-huron-local`. It does not read the default
    kubeconfig.
  - Runs of the first implementation on `huron-local`:
    1. `make k8s-local` three times. I stopped the first run: Keycloak got `OOMKilled` at
       1536Mi. The second run exited 0, with one more `OOMKilled` at 2Gi. The third run, a
       deploy again on the same namespace with a limit of 3Gi, exited 0 with no restart.
    2. `make k8s-local-smoke` three times, each with exit code 0. Each push went through the Ingress, nginx and tusd
       (3 `POST` and 2 `PATCH`), the host read the files, and `huron adm check --hash` from the
       host mount reported no finding. The first run left its `kubectl port-forward` running.
       The fix starts kubectl with no function between, so that the trap stops it.
    3. `make k8s-local-down`, then `make k8s-local` and `make k8s-local-smoke` on the old lake,
       each with exit code 0.
    4. `K8S_LOCAL_PURGE=1 make k8s-local-down`, with exit code 0. The namespace `huron` and the PersistentVolume
       are gone, the lake directory is empty, and `huron:local` is gone from the host and with
       the other four images from the node. The cluster and ingress-nginx stay.
  - Measured on 2026-11-13: ingress-nginx gives its default certificate ("Kubernetes Ingress
    Controller Fake Certificate") to a request with no server name, also when an Ingress with
    no host names the TLS Secret. With the server name `localhost`, it gives the certificate of
    the Secret. So the Ingresses name the host `localhost`.
  - The first implementation gave the Job `huron-migrate` of the overlay `backoffLimit: 6`,
    because its first pod failed while PostgreSQL started. Fix pass 2 replaced this (below).
  - For the first implementation, `make gate` exits 0: 4598 tests passed, 39 deselected, 0
    skipped. 12332 statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `make docs-check` and
    `uv run python scripts/ste_check.py` pass. `kubectl kustomize` renders both directories, and
    the grep of the old task prints nothing.
  - The implementation did not run `make k8s-local-cluster`, because `huron-local` existed. Its
    configuration, which `scripts/k8s-local.sh kind-config` prints, equals the configuration that
    made `huron-local`. The verifiers ran `make k8s-local-cluster` in verifications 1, 3 and 4,
    each with exit code 0.
  - Choices where the plan is silent: the longest seal that the settings allow is
    `upload_hook_timeout`, because the CLI waits that long for a seal. The organizations of
    `deploy/local/huron.yaml` have no root, so the host can mount the lake at another path. The
    Job `huron-lake-init` runs as the service user, not as UID 0. The manifest tests fail, and do
    not skip, when `kubectl` is missing.
  - Verification 1 (2026-11-13): FAIL with six findings. The gate and the cluster cycle passed
    for the verifier, and it made `huron-local` again with `make k8s-local-cluster` (exit 0).
    1. A comment in `deploy/openshift/uploads.yaml` and in `docker-compose.uploads.yml` named a
       plan file.
    2. The Job `huron-lake-init` did not run before the API pod. The first API pod went into
       BackOff, and `clean-locks` failed two times on an empty lake.
    3. `kind-config` also changed the comment of the template, changed a `&` in the lake path
       (bash 5.3), and wrote the path without quotes.
    4. The message for an existing cluster gave `kind delete cluster` without `--kubeconfig`.
    5. Tests read the text of the script and of the nginx template.
    6. `down` deleted before it checked the cluster. With another kubeconfig and context it
       would delete on that cluster.
  - Fix pass 2:
    1. The two comments describe the flags.
    2. `make k8s-local` applies each object but the two Deployments, waits for the two Jobs, then
       applies the Deployments. The Deployments carry the label `app.kubernetes.io/component`.
       The Job `huron-migrate` of the overlay waits for PostgreSQL in an init container, and its
       `backoffLimit: 6` patch is gone. The script starts the API pod again only on a deploy
       again in the same namespace, so that the pod runs the imported image.
    3. `kind-config` changes only the line `hostPath: @K8S_LOCAL_LAKE@`. It writes the path as a
       single-quoted YAML string, and it refuses a relative path and a line break. A test uses
       the path `a&b c'd \ "e" #f: g`.
    4. The message gives the full command with `--kubeconfig`.
    5. The verb `settings` prints the settings of the script. The tests read it, and they check
       `/livez` and `/readyz` through the parsed nginx configuration.
    6. Each verb that uses the cluster first checks that the node binds `K8S_LOCAL_LAKE` at
       `/huron-lake`. `down` does this before a delete. This check also holds when the lake
       directory is gone. A purge also compares the device, the inode and the modification time.
       Tests with a fake `kubectl` and `docker` show no delete for another context, for a node
       that does not bind the lake, and for a purge of a lake that is gone. No command ran
       against `ocp-test`.
  - Measured on `huron-local` after fix pass 2, each command with exit code 0:
    1. `make k8s-local` on an empty lake: each container, init containers included, has 0
       restarts, and there is no `BackOff` event. The other warnings are readiness probes before
       the start and one `FailedScheduling` of the Job before its claim was bound.
    2. `make k8s-local-smoke`: versions 2 to 3 and 3 to 4, and `huron adm check --hash` from the
       host mount reports no finding.
    3. `make k8s-local-down`, then `make k8s-local` on the kept lake: 0 restarts and no
       `BackOff` event.
    4. `make k8s-local` again in the same namespace: the API pod starts again with 0 restarts.
    5. `make k8s-local-smoke`, then `K8S_LOCAL_PURGE=1 make k8s-local-down`. The namespace, the
       PersistentVolume, the lake content and the five images in the node are gone. The cluster
       and ingress-nginx stay, and port 8081 is free.
  - After fix pass 2, `make gate` exits 0: 4609 tests passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `uv run pytest -m integration`: 39 passed. `make docs-check` and
    `uv run python scripts/ste_check.py` pass.
  - Verification 2 (2026-11-13): FAIL with four low findings. It confirmed the six fixes of fix
    pass 2. Its runs: `make gate` with 4609 passed, 12332 statements, 0 missed, 68 clones in 25
    groups; `uv run pytest -m integration` with 39 passed; the cluster cycle with exit code 0,
    0 restarts and no `BackOff` event.
    1. A test comment named a plan, and the help of `make gate` named a section.
    2. `kind-config` refused a line break but not a carriage return, which YAML folds.
    3. The purge test passed without `check_lake` on a host whose user is not 1000:1000.
    4. The comment of `service_group` in `deploy/local/huron.yaml` and the rule in
       `deploy/README.md` did not describe the local cluster.
    The verifier also asked for two hardening items: a purge of `/` or of the home directory,
    and the security context of the init container `wait-for-postgres`.
  - Fix pass 3:
    1. The two texts name no plan and no section. A grep of each file of the change set for
       plan, phase, task and section references found no other.
    2. The script refuses a line break and a carriage return in `K8S_LOCAL_LAKE`, with a test.
    3. A fake `id` gives the UID and the GID of the overlay, which the verb `settings` prints.
       Each refusal test asserts its message. New tests cover the refusal for another user, a
       node that shows another directory, and a purge that empties the lake.
    4. The texts say that GID 1000 has no name in the API image, so `service_group` is only the
       name that `/healthz` reports. `/healthz` on the cluster reports `uid` 1000, `gid` 1000
       and `group` `huron`.
    5. `kind-config`, `cluster` and a purge refuse a lake that is `/` or the home directory, with
       tests.
    6. `wait-for-postgres` has a read-only root filesystem and the seccomp profile
       `RuntimeDefault`. A test rule requires this of each init container of the overlay.
  - Measured on `huron-local` after fix pass 3, each with exit code 0: `make k8s-local` on an
    empty lake (each container 0 restarts, no `BackOff` event, `wait-for-postgres` ran with the
    new security context), `make k8s-local-smoke`, and `K8S_LOCAL_PURGE=1 make k8s-local-down`.
    The cluster stays with ingress-nginx, with no namespace `huron`, no PersistentVolume and an
    empty lake directory.
  - After fix pass 3, `make gate` exits 0: 4621 tests passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `make docs-check` and `uv run python scripts/ste_check.py` pass. The integration tier did not
    run again: fix pass 3 changed no file that it uses.
  - Verification 3 (2026-11-13): FAIL with three small findings. It confirmed the six items of
    fix pass 3. Its runs: `make gate` with 4621 passed, 12332 statements, 0 missed, 68 clones in
    25 groups; the cluster cycle with exit code 0 and 0 restarts. It made `huron-local` again
    with `make k8s-local-cluster` (exit 0).
    1. `check_lake_path` refused the home directory but not a directory above it, for example
       `$HOME/..`. A purge then reached `find … -delete`.
    2. Six refusal tests of `down` repeated one body.
    3. The help of `make k8s-local-down` said that the lake directory stays unless
       `K8S_LOCAL_PURGE=1`. A purge deletes only its content.
    The verifier also asked that the README and the script header name the refusals of a purge.
  - Fix pass 4:
    1. `check_lake_path` compares resolved paths (`realpath -m`). It refuses the home directory
       and each directory above it, also through `/.`, `..` and a symbolic link, and it takes a
       directory beside the home directory. The refusal test of `kind-config` has cases for
       each. The refusal test of `down` had cases for the home directory, `..` and `/` only.
       Fix pass 5 added `/.` and a symbolic link.
    2. The refusals of `down` are one parametrized test with 8 cases. Each case asserts its
       message, exit code 1, and no call of a delete or of `find`. A fake `find` deletes
       nothing. The negative tests of the writer rule and of the tusd rule are two
       parametrized tests.
    3. The help says that the lake content stays unless `K8S_LOCAL_PURGE=1`.
    4. `deploy/README.md` and the header of `scripts/k8s-local.sh` name the refusals of a purge.
  - Measured on `huron-local` after fix pass 4, each with exit code 0: `make k8s-local` on an
    empty lake (each container 0 restarts, no `BackOff` event), `make k8s-local-smoke`, and
    `K8S_LOCAL_PURGE=1 make k8s-local-down`. The cluster stays with ingress-nginx, with no
    namespace `huron`, no PersistentVolume and an empty lake directory.
  - After fix pass 4, `make gate` exits 0: 4629 tests passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `make docs-check` and `uv run python scripts/ste_check.py` pass. The integration tier did not
    run again: fix pass 4 changed no file that it uses.
  - Verification 4 (2026-11-13): FAIL with three small findings in the tests and in this
    record. It confirmed the four items of fix pass 4 and found no defect in the behaviour of
    the script. Its runs: `make gate` with 4629 passed, 12332 statements, 0 missed, 68 clones in
    25 groups; the cluster cycle and a new `huron-local` from `make k8s-local-cluster`, each with
    exit code 0 and 0 restarts.
    1. Two mutants of `check_lake_path` passed all tests: `HOME` without `realpath`, and the
       comparison without the slashes.
    2. The test of the purge asserted the text of the `find` command, not the empty lake.
    3. This record said that the refusal test of `down` had cases for `/.` and a symbolic link.
  - Fix pass 5, tests and this record only:
    1. New tests: `HOME` is a link to the home directory and the lake is the real home directory
       (refused), and a directory beside the home directory whose name is a prefix of the home
       name (taken). The refusal test of `down` has 18 cases. New cases cover `/.`, a link to the
       home directory, another group, a lake that is a file, a node that cannot run `stat`, no
       kubeconfig, two nodes, no node, a node that is not a container, and a bind whose path
       ends with the lake path.
    2. The test of the purge runs the real `find` on a lake in the temporary directory of the
       test. It asserts that the lake directory exists and holds no entry. The refusal tests keep
       the fake `find`.
    3. This record is corrected where it was not true.
    - Mutants: a script in the scratch directory applied 24 single mutants to `check_lake_path`,
      `check_user`, `check_lake`, `preflight` and the purge of `down`, one at a time, and ran
      `tests/unit/test_deploy_manifests.py`. Each mutant made a test fail. The script then
      restored `scripts/k8s-local.sh`, and `cmp` found it equal to the copy. The checks
      `command -v kubectl` and `command -v docker` have no test, because the fakes are on the
      path.
  - After fix pass 5, `make gate` exits 0: 4642 tests passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `make docs-check` and `uv run python scripts/ste_check.py` pass. Fix pass 5 changed no file
    that the cluster or the integration tier uses, so neither ran again.
  - Verification 5 (2026-11-13): FAIL with two small findings in the tests. It confirmed the
    three fixes of fix pass 5 and found the script, the manifests, the gate, the cluster run and
    this record correct. Its runs: `make gate` with 4642 passed, 12332 statements, 0 missed, 68
    clones in 25 groups; up, smoke and a purging down on `huron-local` with exit code 0. The 24
    mutants of fix pass 5 and 31 of its own 33 mutants made a test fail.
    1. The mutant `grep -Fqx` to `grep -qx` of the mount check passed all tests: the lake path
       became a pattern.
    2. The tests gave the host's variables to the script. With `K8S_LOCAL_PURGE=1` or
       `K8S_LOCAL_CONTEXT=other` exported, tests failed.
    It also noted that the fake `docker` does not read the `--format` template, so a mutant that
    removes the line break from that template passes.
  - Fix pass 6, tests and this record only:
    1. A new case of the refusal test of `down`: the lake `<dir>/l.ke` and a node that binds
       `<dir>/lake`. The refusal test of `down` has 19 cases.
    2. The tests run the script with no host variable that starts with `K8S_LOCAL_`, `KUBECONFIG`,
       `FAKE_` or `CALLS`, and with a fixed `HOME` that does not exist, unless a test sets these.
       With `K8S_LOCAL_PURGE=1`, `K8S_LOCAL_CONTEXT=other`, `K8S_LOCAL_LAKE=/`,
       `K8S_LOCAL_KUBECONFIG=/nonexistent`, `KUBECONFIG=/nonexistent`, `FAKE_NODE="a b"`,
       `CALLS=/dev/null` and `HOME` in the scratch directory exported, the 125 tests of the file
       pass. Verification 6 found this sentence false, and fix pass 7 corrects it: the other
       tests that start a process run programs that do not read these variables, so a host
       value does not change their result. Some of them give the full host environment to the
       program: `tests/support/crash.py` keeps each host variable but `HURON_*`,
       `tests/support/state_child.py` removes only `HURON_*`, `COV_CORE_*` and `XDG_*`, and
       `tests/unit/storage/test_organizations.py` and
       `tests/unit/storage/test_provision_catalogs.py` run `sh` with the full host environment. `tests/support/devprovision.py` builds the
       environment from nothing.
    - Mutants ran in a copy of the tree in the scratch directory, with the virtual environment
      of the work tree. The script of the work tree did not change: its SHA-256 before and after
      is equal. The new mutant (`grep -qx`) and the 24 earlier mutants each made a test fail, 25
      of 25.
    - The fake `docker` still does not read the `--format` template. A test of that template
      needs the real `docker`, so the mutant stays. With the real `docker` the mutant refuses each
      cluster, so the check stays closed.
  - After fix pass 6, `make gate` exits 0: 4643 tests passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `make docs-check` and `uv run python scripts/ste_check.py` pass. Fix pass 6 changed no file
    that the cluster or the integration tier uses, so neither ran again.
  - Verification 6 (2026-11-13): FAIL with one gap in a test of a safety check and one false
    sentence in this record. It confirmed the two fixes of fix pass 6 and found the script, the
    manifests, the gate and the cluster run correct. Its runs: `make gate` with 4643 passed,
    12332 statements, 0 missed, 68 clones in 25 groups; up, smoke and a purging down with exit
    code 0.
    1. `down` tested `K8S_LOCAL_PURGE == 1` two times: before the checks and before the delete.
       A mutant of the second test to `-n` or `== 1*` passed all tests. With
       `K8S_LOCAL_PURGE=yes` that mutant skips the checks and runs `find … -delete`.
    2. The sentence of fix pass 6 about the other tests that start a process was false.
    It also found that the tests let bash startup variables (`SHELLOPTS`, `BASH_ENV`) through.
  - Fix pass 7:
    1. `down` decides the purge one time, in the variable `purge`, and the checks and the delete
       read it. Only the value `1` purges. A new parametrized test runs `down` with
       `K8S_LOCAL_PURGE` set to `0`, `yes`, `10` and the empty string: each exits 0, deletes the
       namespace and the volume, and calls no `find` and no image removal. The header of the
       script and `deploy/README.md` say that only the value `1` purges.
    2. The sentence of fix pass 6 is corrected (above).
    3. The tests run the script without `BASH_ENV`, `ENV`, `SHELLOPTS`, `BASHOPTS` and the
       variables that start with `BASH_FUNC_`. With these exported (`SHELLOPTS=xtrace` and a
       `BASH_ENV` file that exits 3, among others), and with the variables of fix pass 6, the
       129 tests of the file pass.
    - Mutants ran in a new copy of the tree in the scratch directory: the 25 earlier mutants
      and 4 new ones on the purge decision (`-n`, `== 1*`, the delete drifting to `-n`, the
      checks never running). Each of the 29 made a test fail. The script of the work tree did
      not change during the mutant run.
    - The SHA-256 of `scripts/k8s-local.sh` after fix pass 7 is
      `8f250abede4ec33ffa78eaeee10ce854bac9e4a9e05fb9242997ec43d9697619`.
  - Measured on `huron-local` after fix pass 7, each with exit code 0:
    1. `make k8s-local` on an empty lake: each container 0 restarts, no `BackOff` event.
    2. `make k8s-local-smoke`: versions 2 to 3 and 3 to 4, and the check reports no finding.
    3. `make k8s-local-down`: the lake keeps `.huron`, `.tus-uploads` and the three organization
       directories.
    4. `make k8s-local` on the kept lake: each container 0 restarts, no `BackOff` event, and no
       start again of the API pod.
    5. `K8S_LOCAL_PURGE=1 make k8s-local-down`: the lake directory has no entry. The namespace,
       the PersistentVolume and the images are gone. ingress-nginx runs, and port 8081 is free.
  - After fix pass 7, `make gate` exits 0: 4647 tests passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `make docs-check` and `uv run python scripts/ste_check.py` pass. The integration tier did not
    run again: fix pass 7 changed no file that it uses.
  - Verification 7 (2026-11-13): FAIL with three groups of surviving comparison mutants in the
    tests. It found the script, the manifests, the gate, the cluster cycle and this record
    correct, and confirmed the three items of fix pass 7. Its runs: `make gate` with 4647
    passed, 12332 statements, 0 missed, 68 clones in 25 groups; the cluster cycle with exit code
    0, with a down with `K8S_LOCAL_PURGE=yes` that left the lake as it was.
    1. The purge decision: `== *1`, `=~ 1$` and `== 1 || == true` passed all tests.
    2. The context check: a prefix, a suffix and a regex match passed all tests.
    3. The user check: a regex, a prefix and a suffix match passed all tests.
  - Fix pass 8, tests and this record only. The script did not change: its SHA-256 is still
    `8f250abede4ec33ffa78eaeee10ce854bac9e4a9e05fb9242997ec43d9697619`.
    1. The comparisons of the safety checks:
       - C1 `preflight`: `[[ -f "$kubeconfig" ]]`.
       - C2 `preflight`: `[[ "$current" == "$context" ]]`.
       - C3 `preflight`: `[[ -n "$nodes" && "$nodes" != *" "* ]]`.
       - C4 `preflight`: the exit code of `docker inspect --type container`.
       - C5 `preflight`: `grep -Fqx -- "$lake=$node_lake"`.
       - C6 `check_lake_path`: `[[ "$lake" == /* ]]`.
       - C7 `check_lake_path`: `[[ "$lake" != *[$'\n\r']* ]]`.
       - C8 `check_lake_path`: `[[ "$home/" != "${real%/}/"* ]]`, with the two `realpath -m`.
       - C9 `check_user`: `[[ "$(id -u):$(id -g)" == "$uid:$gid" ]]`.
       - C10 `check_lake`: `[[ -d "$lake" ]]`.
       - C11 `check_lake`: `[[ "$here" == "$there" ]]`, with the two `stat -c '%d %i %Y'`.
       - C12 `down`: the purge decision `[[ "${K8S_LOCAL_PURGE:-}" == 1 ]]`.
       - C13 and C14 `down`: the two readers `[[ "$purge" == yes ]]`, before the checks and
         before the delete.
    2. A driver in the scratch directory made the standard mutants of each comparison: `==` and
       `!=` swapped, a prefix, a suffix, a substring and a regex match, each operand alone,
       dropped `grep` flags (`-F`, `-x`, `-q`, all three, and `-v` added), `-d`, `-e`, `-f`, `-n`
       and `-z` swapped, `fail` changed to `true` and to `say`, the check removed, and each part
       of `uid:gid` and of the `stat` format dropped. The driver of fix pass 8 did not drop
       `--`; fix pass 9 added that mutant (below). It ran each mutant in a copy of the tree in
       the scratch directory: 137 mutants, 128 make a test fail. The 29 mutants of the earlier
       passes ran again there: 29 of 29 make a test fail. The script of the work tree did not
       change during the runs.
    3. The new test cases: the values `01`, `1 `, ` 1` and `true` of `K8S_LOCAL_PURGE`, each also
       with the lake directory gone; the contexts `kind-huron-local-2` and `x-kind-huron-local`;
       the UID 11000 and the GID 10000; a kubeconfig that is a directory; a node that shows
       another directory with the same time as the lake, so that only the inode differs; and a
       lake at the root with the name of the home directory. The fake `docker` now runs the real
       `stat`, with the format of the script, on the directory that the test gives the node.
    4. The 9 mutants that passed all tests in fix pass 8: C5 `grep` without `-q`, C11 without
       the device and C11 without the time on the two sides, and C13 and C14 with a prefix, a
       substring and a regex match each. Fix pass 9 gives the full list of the survivors and
       the reason for each one.
    5. `BASH_FUNC_` moved from the group of the script variables to the group of the shell
       variables.
  - After fix pass 8, `make gate` exits 0: 4666 tests passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `make docs-check` and `uv run python scripts/ste_check.py` pass. Fix pass 8 changed no file
    that the cluster or the integration tier uses, so neither ran again.
  - Verification 8 (2026-11-13): FAIL with one surviving mutant. It confirmed the three fixes of
    fix pass 8. Its runs: `make gate` with 4666 passed, 12332 statements, 0 missed, 68 clones in
    25 groups; the 148 manifest tests in their normal order, in reverse order and with the hostile
    environment; up, smoke and a purging down with exit code 0; its own 192 standard mutants, 176
    of which make a test fail.
    1. C5 without `--` (`grep -Fqx "$lake=$node_lake"`) passed all tests. With
       `K8S_LOCAL_LAKE=-ve`, `grep` reads `-v -e "=/huron-lake"`, each bind line matches, and a
       `down` with no purge deletes the namespace and the PersistentVolume on a node that does
       not bind the lake.
    It also found survivors that this record did not list: the suffix `*yes` of C13 and C14,
    C3 and C7 as unanchored literal regexes, C8 as an anchored literal regex, and C11 with only
    the inode on the two sides.
  - Fix pass 9, one test case and this record. The script did not change: its SHA-256 is still
    `8f250abede4ec33ffa78eaeee10ce854bac9e4a9e05fb9242997ec43d9697619`.
    1. A new case of the refusal test of `down`: `K8S_LOCAL_LAKE=-ve`, with the message "does not
       bind -ve at /huron-lake, so it is not the local cluster". The refusal test of `down` has
       26 cases, and the file has 149 tests. In the copy of the tree, the original passes 149 of
       149, and the mutant without `--` fails only this case.
    2. The driver now also drops `--` from each command of the safety code that takes it: the
       `grep` of C5 and the two `realpath -m --` of C8. It also makes the forms of verification
       8: the suffix `*yes` of C13 and C14, C3 and C7 as unanchored regexes, C8 as an anchored
       literal regex, and C11 with only the inode. It ran 146 mutants in a new copy of the tree:
       129 make a test fail, and 17 pass all tests. The script of the work tree did not change.
    3. The 17 mutants that pass all tests, and why each one is accepted:
       - C3, the space as an unanchored regex (`! "$nodes" =~ " "`): the same test as the
         pattern `*" "*`.
       - C5 `grep` without `-q`: the exit code is the same. Only the bind line goes to the
         output.
       - C7 as an unanchored regex (`! "$lake" =~ [$'\n\r']`): the same test as the pattern.
       - C8 as an anchored literal regex (`! "$home/" =~ ^"${real%/}/"`): the quoted part is
         literal, so this is the same prefix test.
       - C8, the `realpath` of the lake without `--`: the line before refuses a lake that does
         not start with `/`, so no lake starts with `-`.
       - C8, the `realpath` of `HOME` without `--`: the result changes only when `HOME` starts
         with `-`. Such a `HOME` is not an absolute path, and a login does not set it.
       - C11 without the device on the two sides: a test needs two filesystems with the same
         inode number. The inode and the time stay compared.
       - C11 without the time on the two sides: the same device and inode are the same
         directory, which has one time.
       - C11 with only the inode on the two sides: a different result needs the same inode
         with another device or time, as above.
       - C13 and C14, with a prefix, a suffix, a substring and a regex match each (8 mutants):
         `purge` holds only `no` or `yes`, which the line before sets, so these mutants give the
         same result.
  - After fix pass 9, `make gate` exits 0: 4667 tests passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
    `make docs-check` and `uv run python scripts/ste_check.py` pass. Fix pass 9 changed no file
    that the cluster or the integration tier uses, so neither ran again.
  - The nightly macOS job runs `pytest -m unit`. No test has the marker `unit`, so pytest stops
    with exit code 4 before and after D4. That job does not run the manifest tests.

### D5 Measurements on the ONTAP export (part of old M11.13)

- Intent: the facts that only the real export can give. This task needs the storage operator.
- Measure on a private directory of the export, and record the commands and the output:
  1. Setgid inheritance: the procedure of the old plan (directory `2750 U:S`, then `mkdir`,
     `touch`, `stat` as the service UID).
  2. A hard link from the object area to a collection directory of each organization root.
  3. A rename over a file that a reader on another client holds open, and a removal of a file
     that a process on the same client holds open. Record what the directory then lists.
  4. The time to copy and hash 10 GiB through the mount. Compare it with the tusd hook timeout.
  5. What `statvfs` reports with the export's quota and snapshot settings.
- A result that contradicts the design of plan 2 stops this plan. Correct the design first.
- Verification: the record is in `docs/operator.md` under a dated heading.
- Dependencies: D2. This task can run as soon as the operator is available.
- Status: blocked (2026-11-13). This workstation has no mount of the export (`/data1` is local
  ext4) and the storage operator is not available. No measurement was made.

### D6 Documentation (old M11.12)

- Changes to the old task. Add:
  - The publication model: accepted, pending, mixed visibility during a pending commit.
  - The single-writer rule: never two writable pods, and what the API does when it loses its lock.
  - The blocked request: how to read it, `retry`, `abandon`, and the manual procedure for a
    request with done steps and a lost object.
  - Capacity settings and the upload lifetime.
  - Backup: PostgreSQL and the lake must be restored to the same point. A restore of one of them
    alone is not supported.
  - A reader on another client can get a stale-handle error after a file is replaced.
  - Add a supersession note to `docs/adr/0008-uploads-through-tusd.md`. Keep its history.
- Verification: the old task's entry, `make docs-check`, `uv run python scripts/ste_check.py`.
- Dependencies: D4, D5.
- Owner decision (2026-11-13): "do D6 now out of order". D6 runs before D5. D6 does not write
  the D5 measurement record and does not give a measured value for the export. Where a text
  depends on a D5 result, it says that the measurement is not yet made.
- Status: complete (2026-11-13). Verification 10 passed after 10 implementation passes;
  verifications 1 to 9 failed, each on text findings. Gate of verification 10: `make gate` exit
  0, 4667 passed, 39 deselected, 0 skipped, 12332 statements with 0 missed, 68 clones in 25 groups
  against the baseline of 69 in 25. The integration tier, the web gate and the documented
  procedures on a cluster or on the export did not run. Implementation pass 1 (2026-11-13):
  - Changed: `docs/operator.md` (ACL text removed, an organization without a root at
    `<lake_path>/<name>`, and new sections for the lake and its users, the upload pod, share groups,
    install order, symbolic links, one writer, the publication of a commit, blocked commit
    requests, capacity and lifetime, cleanup, "Helm: not yet delivered", the local cluster
    `huron-local`, "Setgid measurement (pending)" and backups), `docs/architecture.md`,
    `docs/user-guide.md`, `docs/concepts/how-huron-works.md`, `docs/concepts/raw-ingest.md`,
    `docs/concepts/metadata-and-schemas.md`, `docs/concepts/access-and-roles.md`,
    `docs/web-design.md` (a dated amendment, and the ACL command named in words),
    `docs/adr/0008-uploads-through-tusd.md` (a supersession note, the record kept), `README.md`,
    `deploy/README.md`, `dev.env` (comment), `CONTEXT.md` and the labels of the two component
    diagrams in `web/docs-site/public/diagrams/`.
  - The D5 measurements are not made. Each text that depends on one says so.
  - The README note on `INTERNAL` for `-1e31` is removed: `huron.pkg.canonical` writes integers
    of any size since commit `a666c886`, and the contract suite covers `-1e31`.
  - Runs: `make gate` exits 0 with 4667 passed, 39 deselected, 0 skipped, 12332 statements, 0
    missed, 68 clones in 25 groups. `make docs-check` and `uv run python scripts/ste_check.py`
    pass. The greps of old M11.12 pass. The integration tier and the web gate did not run.
  - Verification 1 (2026-11-13): FAIL with seven small findings. Fix pass 2:
    1. `raw-ingest.md` and `architecture.md`: the dry run sends the path, the size and the
       `sha256` of each add, and the upload ID of a sealed upload.
    2. `operator.md` "Reading `huron adm check`": the check as `U` with `oc exec -it deploy/huron
       -- sh`, with the configuration and the state in `/tmp`, `HURON_API_URL`, `HURON_ISSUER`,
       `HURON_MOUNT_PREFIX` and `huron login --device`. Not tested on a cluster.
    3. `operator.md`, the lost-object procedure: continue only for `state = 'sealed'`, the copy
       goes into the API pod with `oc cp` and `install -m 0644`, and the queries use
       `commit_requests.id`. Not tested on a cluster.
    4. `operator.md`: the token path is `${XDG_STATE_HOME:-$HOME/.local/state}/huron/tokens.json`.
    5. `CONTEXT.md` read again in full. Terms of features that the code does not have are gone
       (catalog config, config version, file stamp, express slot, bulk metadata edit, move,
       staging directory, pin, resolved, persistence point, prefill, stale staged entry,
       reconciler, sweep, orphan directory, roles claim, loopback NFS tier). Role, grant, Huron
       JWT, working copy, lake path, share group, repair, schema and check now match the code.
    6. `operator.md`: one list of pending measurements. ADR 0008: the closing sentence is its
       own paragraph.
    7. The lines below stand in for the Execution notes that old M11.12 asks for, because
       `IMPLEMENTATION_PLAN.md` is not edited in this plan.
    Also: `operator.md` and `deploy/README.md` name the timeouts that bound a final `PATCH`
    (nginx `proxy_read_timeout 120s`, tusd `-request-completion-timeout=60s` and
    `-network-timeout=2m`). The padding of the access row in `web-design.md` is fixed.
  - Execution notes for old M11.12. They stand in for the lines in the Execution notes of
    `IMPLEMENTATION_PLAN.md`, which this plan does not edit. They say where the built system
    differs from section 3, sections 4.1, 6 and 12, ADR 0008, `CONTEXT.md` and `AGENTS.md`:
    - Sections 3, 4.1, 6 and 12 of `IMPLEMENTATION_PLAN.md` differ from the built system. D-7
      and D-8 of section 3 (a synchronous commit, no idempotency keys) are replaced by commit
      requests with request IDs. The row of `huron-api` in section 4.1 (placement, the unlink
      of removed files, the sweep of `.tus-uploads`), sections 6.2 and 6.3 (a placed file, the
      push write path with `Placer`, receipts and removal rows) and the risk register rows of
      section 12 on placement, receipts, the removal race and the sweep describe the replaced
      design. `IMPLEMENTATION_PLAN.md` is not edited: plan 2 records the replaced decisions in
      its section "Design" ("This section replaces decisions D-7 and D-8 … and the upload flow
      of its uploads amendment"), and `M11_PLANS.md` says to list replaced decisions in each
      plan and not to edit the old plan. The documents of D6 describe the built system.
    - ADR 0008: the publication design replaces the placement in `pre-finish`, the receipts, the
      latest placement, the removal rows, the background unlink, the `pre-terminate` hook and
      the two-replica window. A supersession note at the top names each part. The record stays.
    - `CONTEXT.md`, compared with `git show HEAD:CONTEXT.md` term by term:
      - Dropped, with no successor: Bulk metadata edit, Catalog config, Config version, Express
        slot, File stamp, Identifier forms, Loopback NFS tier, Move, Orphan directory,
        Persistence point, Pin, Prefill, Resolved, Roles claim, Staging directory, Stale staged
        entry and Sweep.
      - Dropped and replaced: Commit plan by Commit entry, Org base schema by Base schema
        (`huron-base`), Placement by Seal and Publication, Receipt by Seal and Object area,
        Reconciler by Drift check, Role mapping by Grant.
      - Added: Base schema, Cleanup, Commit entry, Drift check, Grant, Object area, Publication,
        Reconcile (the startup reconcile of declared organizations), Seal and Writer lock.
      - Rewritten to match the code: Catalog, Segment, Identifier, Metadata schema,
        Organization, File, Commit, Commit state, Overwrite, Publish, Mount prefix, Partial,
        Upload, Lake path (an organization directory may be its own mount), Share group, Repair,
        Working copy, Context, State directory, Company IdP, Group directory, Huron JWT, Role,
        Finding and Hierarchy, and the Relationships, the example dialogue and the Flagged
        ambiguities.
    - `AGENTS.md` (fix pass 4): the layout block differed from the tree. `lake/` now also names
      `uploads`, `publications` and `repairs`, `storage/` names seal, publication, repair and
      provisioning, and `api/` names `disk/`, which holds the lake work. The dependency rules
      and the gate of `AGENTS.md` match the code.
  - Verification 2 (2026-11-13): FAIL with five findings. Fix pass 3:
    1. `operator.md` "Reading `huron adm check`": no account checks everything. On a workstation
       an account in `G` and every share group checks the share groups but not the object
       areas. In the API pod, `U` reads everything, but the image resolves no LDAP group, so
       each catalog with a share group gives `share_group_mismatch` and the check exits 1. The
       row of `share_group_mismatch` says so. The help of `huron adm check` still says that a
       complete check needs the service user in an API pod; that text is code and is not
       changed here.
    2. `operator.md` "The upload pod" and `deploy/README.md`: the procedure for a longer
       `upload_hook_timeout` names `-request-completion-timeout` (equal to
       `-hooks-http-timeout`), `-network-timeout` (longer) and the grace periods, with an
       example for 15 minutes. nginx (120 s) and the Route (3600 s) need no change.
    3. `operator.md`, the lost-object procedure: the update converts an inode of 2^63 or more
       to the signed `bigint` (`n - 2^64`), as `signed_inode` does. The copy is synced with
       `sync <file> <object area>`.
    4. The execution notes above cover sections 3, 4.1, 6 and 12, and list each term of
       `CONTEXT.md` by name.
    5. `CONTEXT.md`: the "sweep" ambiguity names the web's session sweep. File names the inode
       of its object. Drift check no longer contradicts the `Reconciler` class.
  - Verification 3 (2026-11-13): FAIL with four small text findings. Fix pass 4:
    1. `architecture.md`: `core.lake` lists its ten areas, uploads, publications and repairs
       included. The dependency diagram shows the imports of the code: `core.lake` also imports
       `core.security.broker.keys`, `schema` and `pkg`; `core.security` imports only `pkg`; the
       CLI imports `core.lake` organizations and publications, `schema` and `pkg`.
    2. `AGENTS.md`: the layout block (see the execution note above).
    3. A catalog can have one share group, and without one only `U` and the members of `G` read
       it: `README.md`, `how-huron-works.md` and `operator.md` (Prerequisites, LDAP groups).
    4. `operator.md`: an account that cannot read an entry gets `unreadable` outside the object
       areas. The check skips an object area for every account but `U`, with no finding.
    Also: `raw-ingest.md` says how `huron status`, `huron adm verify-mounts` and
    `huron adm check` report a refused marker, in place of "exit code 8". The description of
    the two component diagrams no longer says that the CLI reads the share.
  - Verification 4 (2026-11-13): FAIL with four small text findings. Fix pass 5:
    1. `operator.md` "The API's mount" and `raw-ingest.md` "Drift detection": the walks do not
       enter `.huron-objects`. `huron adm check` lists each object area as `U` only, and reports
       there probe files, links and entries that it cannot stat.
    2. The provision commands of the storage admin are named as the exception to "the API writes
       the share" in `architecture.md` (intro, the state table), `user-guide.md` (glossary
       "share"), `README.md`, `how-huron-works.md`, `raw-ingest.md` and ADR 0008. The API does
       not write the markers. The export rules of `operator.md` and `deploy/README.md` give the
       storage admin's machine a read-write mount.
    3. `raw-ingest.md` "The marker": a symbolic link and a marker that the account cannot read,
       for `huron adm verify-mounts` and `huron adm check`. The behaviour of `verify-mounts` is a
       code defect (below).
    4. `operator.md`, the findings table: `mode_drift` states that repair fixes the bits only
       while the API is in the directory's group, and gives `chmod 2750` as root and
       `huron adm provision-catalogs`. Each row was checked against the code. `file_missing`
       and `file_changed` now say that a replace or a removal of a file with another inode
       blocks with `foreign_entry`, and give the order that works. `symbolic_link` points to the
       work to run again.
    Also: `user-guide.md` gives the default of `upload_hook_timeout` (15 minutes) and the 60 s of
    the base and the development stacks. Rule 8 of `architecture.md` names
    `core.lake.publications.planning`. Self-review: 344 added lines with an absolute word were
    read. These changed: the "one writer" sentences of `README.md`, ADR 0008,
    `architecture.md` (three), `how-huron-works.md` (two) and `raw-ingest.md` (two), the
    export rules and the read-write mounts of `operator.md` (three) and `deploy/README.md`,
    the space of the object area in `operator.md`, and "each request but `OPTIONS`" in
    `user-guide.md`.
  - Verification 5 (2026-11-13): FAIL with two medium and two small findings. Fix pass 6:
    1. The standing read-write export for the storage admin's machine (fix pass 5) is reverted.
       `operator.md` (Prerequisites, "The export rules", the new "Where the storage admin
       works", "Adding an organization", "Share groups", "Install order"), `deploy/README.md`
       ("The export rules", "Install order", "Preparing the organization directories") and
       `architecture.md` (the NFS share row) now say what `IMPLEMENTATION_PLAN.md` says: the
       export is read-write only for the clients of the API pod and the upload pod (lines 360 to
       362); the root scripts run on a machine with a writable mount, "the storage system's own
       shell, or a client that the export does not squash" (lines 1456 to 1458); step 5 of the
       design makes the export read-only for every other client after the provisioning. The
       install order keeps the plan-4 change that the lake path and the organizations are
       prepared before the deploy, with `--config`. "Clients mount the share read-only" became
       "Workstations …" in `raw-ingest.md` and `access-and-roles.md`.
    2. `operator.md`, new section "Missing or changed files": how an operator compares the
       recorded inode (`huron.files.inode`) with `stat -c %i`; the order before a push; after a
       block with no done entry (abandon, then `huron rm` two times); after a block with a done
       entry (no procedure, to the developers). The text says that these steps are derived
       from the code and not run. The 10-minute wait before exit code 6 is stated in
       `user-guide.md`, `raw-ingest.md` and `operator.md`.
    3. `operator.md`, the `mode_drift` row: the command for each kind of entry (a declared
       organization, an organization that is not declared, a catalog, namespace or collection,
       a directory inside a collection, a file).
    4. The writer exception reads "apart from tusd's own files and the provision commands" in
       `README.md`, `architecture.md` (intro and the alt text) and the `<desc>` of both
       component diagrams.
  - Open question for the owner (fix pass 6): where does the storage admin run a provision
    step after step 5 of the install order, when the export is read-only for every client but
    those of the API pod and the upload pod? `IMPLEMENTATION_PLAN.md` lines 1455 to 1482 give
    a writable, unsquashed machine for the install only. Later steps need it too:
    `huron adm provision-orgs` for a new organization, `huron adm provision-catalogs` for each
    new catalog with a share group, a `chmod` as root for `mode_drift`, and the deletion of a
    file in "Missing or changed files". Is an in-cluster Job on the read-write claim, as
    `deploy/local/lake-init-job.yaml` does for the local cluster, the production route? The
    documents say that the design gives no route.
    Facts from the code, added in fix pass 7, not a recommendation: `oc exec` into the API pod
    reaches the API at `127.0.0.1:8080` also while the pod is not ready, because readiness only
    takes the pod out of the Service. The pod runs as `U` with the lake mounted read-write.
    `huron adm provision-orgs --config <file>` makes no API request
    (`src/huron/applications/cli/provisioning.py` `from_file`). As `U`, the provision steps
    (`src/huron/core/storage/provision.py` `_directory`, through `PosixStorage.make_directory`
    and `huron.pkg.fs.posix.make_dir`, a `mkdirat` then an `fchmod`) can make `<root>/<org>`
    when `U` may write the root: as its owner, through `G`, or through other. `set_owner` and
    `set_mode` then need no root, because `U` owns the new directory and is in `G`, and
    `change_owner` makes no `chown` for an entry that has the owner already. As `U` they cannot
    make a directory in a root that `U` may not write, and cannot give an entry another owner.
    Each run also prepares the lake path and `.tus-uploads` (`prepare_lake`). As `U` this works
    only while `U` owns the lake path and, when it exists, `.tus-uploads`. `U` can set the group
    `G` itself. `huron adm provision-catalogs` gives
    a share group, which `U` can do only as a member of that group. In the pod, `/etc/huron/huron.yaml` is the applied configuration,
    not an edited one, and the image does not resolve `service_group`, so `--gid` is needed.
    The user documents do not give this route.
  - Design gaps recorded by D6 (no procedure in the code):
    - A request with a done entry and a lost object, when no copy with the same SHA-256 exists
      (`operator.md`, "A request with done entries and a lost object").
    - A request with a done entry that blocks on a missing recorded file, or on a recorded file
      with another inode: a retry blocks again with `foreign_entry` (`AddFile.old_inode` in
      `src/huron/core/storage/publication.py`, `_add`), and an abandon is refused
      (`_abandon` in `src/huron/core/lake/publications/operations.py`).
      An unverified idea for the developers, not documented: an operator could write the inode
      of the file now at the path into `huron.files.inode` before a retry, because the step reads
      the old inode from that row (`_targets`, `src/huron/core/lake/publications/operations.py`
      lines 546 to 557). Nobody has checked this.
  - Verification 6 (2026-11-13): FAIL with one medium and five low findings. Fix pass 7:
    1. `operator.md` "Adding an organization", the `org_dir_missing` row and `deploy/README.md`
       "Preparing the organization directories": the new organization is prepared first, with
       `huron adm provision-orgs --config <edited huron.yaml> --org <org>`, which makes no API
       request, and the configuration is applied after it. While a declared organization has no
       directory or marker, the API is not ready for every organization. The text on `--config`
       names `service_uid`, the resolution of `service_group` on the machine, `--uid` and
       `--gid`.
    2. `deploy/README.md`: "steps 5 and 8 of the install order, before step 9".
    3. and 4. `operator.md` "Missing or changed files": the signed inode has one wording in both
       places, and the operator gets the collection ID and the path in the collection from the
       finding with `huron -o json describe collection` and `huron get files`.
    5. The changed-in-place case stages the file with `huron add … --as …` before `huron push`.
    6. `huron rm` and `huron add` stop until a `huron push` gets the end of the request.
    Also: the storage admin moves the file away or keeps a copy before a delete; the backup text
    covers `.tus-uploads` on another filesystem; the provision commands also give catalog
    directories their share groups (`README.md`, `raw-ingest.md`, `how-huron-works.md`, the
    glossary). The open question and the design-gap record have the facts above.
  - Verification 7 (2026-11-13): FAIL with one low finding in this record. Fix pass 8: the
    facts in the open question now give the code's condition for `U` (a root that `U` may write:
    as its owner, through `G`, or through other), and add that each run also prepares the lake
    path. Residual notes: install step 7 of `operator.md` runs `verify-mounts` on the machine of
    step 5 and skips the second `provision-orgs`; "First steps after deployment" names the
    machine it needs; install step 5 of `deploy/README.md` uses only the two `provision-orgs`
    lines of its block, and step 7 runs `verify-mounts`; "Then" became "In that case".
  - Verification 8 (2026-11-13): FAIL with two low text findings. Fix pass 9: the open question
    now gives the condition of `prepare_lake` for `U` (it owns the lake path and an existing
    `.tus-uploads`; it can set `G` itself). `operator.md` "The mount prefix" says that
    `provision-orgs` runs as root, or as `U` while `U` owns the lake path. Residual notes:
    install step 5 of `operator.md` sets `mount_prefix` first and states the `lake_path` check;
    steps 5, 7 and 8 of both pages name a client with the CLI and a lake mount where the CLI is
    needed, and the emitted root scripts for the storage system's own shell, with the same lake
    path there and, for the catalog script, share group names that the shell resolves;
    `deploy/README.md` names a missing `service_group` as a reason for `--gid`; the label of
    implementation pass 1 no longer says "not yet verified".
  - Verification 9 (2026-11-13): FAIL with one low finding. Fix pass 10: `operator.md` "The mount
    prefix" now says only that `provision-orgs` writes the marker as root. The clause for `U` left
    out that `U` must also own an existing `.tus-uploads` (`prepare_lake`).
  - Defect for a later code task (found in D6, not fixed: D6 changes no code):
    - The help of `huron adm check` (`src/huron/applications/cli/commands/adm.py` lines 198 to
      200) and its generated reference
      (`web/docs-site/src/content/docs/reference/cli/adm.md` lines 116 to 118) say that a
      complete check needs the service user, "for example in an API pod", and that an account
      in the service group and every share group "can also do a complete check". In the API
      pod the CLI resolves no LDAP group, so each catalog with a share group gives
      `share_group_mismatch`. An account in `G` does not see the object areas.
      `docs/operator.md` "Reading `huron adm check`" gives the true behaviour.
    - The comment of `MAX_UPLOAD_HOOK_TIMEOUT` (`src/huron/applications/api/settings.py`
      line 61) says that the hook timeout stays below the 3600 s of nginx. nginx waits 120 s
      (`deploy/openshift/nginx-uploads.conf.template`, `proxy_read_timeout`).
    - `huron adm verify-mounts` stops at the first organization whose marker it cannot read or
      whose directory or marker is a symbolic link, with no row for the others. `marker_state`
      (`src/huron/core/storage/marker.py` lines 140 to 149) raises again a `StorageError` that
      has no `state`, and `_mount_row` (`src/huron/applications/cli/commands/adm.py` lines 666
      to 672) does not catch it. The command then exits with `SYMLINK_IN_LAKE` and code 1, or
      with `STORAGE_FAILED` and code 8. For the marker at the mount prefix, `prefix_state`
      (`src/huron/applications/cli/mount.py` lines 126 to 130) turns the same errors into exit
      code 8. `docs/concepts/raw-ingest.md` "The marker" describes this behaviour.

### D7 Helm chart and production values (old M11.13)

- Changes to the old task:
  - The chart allows one writable replica only. The schema refuses another value.
  - The values include the capacity settings and the upload lifetime, with no unlimited default.
- Open item: Helm is not on this workstation. The owner supplies Helm 3 or a cached image.
  Closed (2026-11-13): by the owner's instruction, Helm v3.22.1 is installed in
  `~/.local/bin/helm` from `get.helm.sh`, with the published SHA-256 checked.
- Verification: the old task's entry.
- Dependencies: D5, D6.
- Owner decision (2026-11-13): "yes, run D7 after D6 passes". D7 runs before D5. The chart and
  its notes give no measured value for the export. Where a text or a value depends on a D5
  result, it says that the measurement is not yet made.
- Status: in progress

## Escalation (D2, 2026-11-12)

Task D2 "The check and provisioning (old M11.9)" failed its third verification. The workflow
stopped there. D3 to D7 were not started. D1 is complete (commit `a433b469`).

### State of the tree

- The D2 work is in the working tree and is not committed: 39 paths against `a433b469`
  (34 changed files, one renamed file and 4 new files). The renamed test file is staged as a
  rename (`tests/unit/cli/test_check_and_acl.py` to `test_check.py`).
- The tree is not broken. `make gate` exits 0 on it in each verification. The last run (fix
  pass 5): 4455 passed, 24 deselected, 0 skipped; 12325 statements, 0 missed (11755 with 0
  missed before D2); duplication 68 clones in 25 groups against the baseline of 69 in 25.
- `uv run python scripts/cli_reference.py --check`, `make docs-check` and both acceptance greps
  of old M11.9 pass.
- Nothing was reverted, because the gate passes and each open finding is small.

### Verification 1 (FAIL: one medium, three small)

1. Medium. `check_organization` reported `unreadable` for a correctly closed `0700` object area
   to each account other than the service user. `huron adm check` then exited 1 for those
   accounts. This contradicted "the check skips `.huron-objects`".
2. Small. The `unreadable` row of `docs/operator.md` disagreed with the help of `adm check`.
3. Small. `ORGANIZATION_STEPS` and `CATALOG_STEPS` in `adm.py` were public and were used only
   in that module.
4. Small. One elliptical sentence in `docs/concepts/raw-ingest.md`.

Accepted in this verification: `provision-catalogs` without `--uid`; the `Owner` value;
`prepare_lake` in place of `mark_lake`; `walk` that yields `unreadable` (each caller was
checked); `--config` on `provision-orgs` only, with no API request; the check gets a read-only
`ShareReader`.

### Verification 2 (FAIL: one medium, three small)

All findings of verification 1 were fixed.

1. Medium. `provision_catalogs` selected a catalog that the CLI cannot read. Section 3 says
   that such a catalog is not selected for that reason only.
2. Small. Two finding details in `check.py` broke strict STE (a fragment, and "it" without an
   antecedent).
3. Small. The tests held only some `PermissionDenied` refusals to both adapters. One test name
   was stale. The docstring did not name `context["error"]`.
4. Small. `test_status_refuses_a_collection_directory_that_is_a_link` asserted `exit_code != 0`
   and a substring.

Confirmed in this verification: the new `PermissionDenied(StorageError)` changes no behaviour
at a `StorageError` catch site, and the API contract is the same; a refused object area gives
exit 0; the `NEEDS_SHELL` marker complies (0 skipped).

### Verification 3 (FAIL: three small)

All findings of verification 2 were fixed. The verifier judged each finding below "fixable
within the current plan" and "not a plan defect".

1. Small. `src/huron/core/storage/provision.py`, `Provisioner.provision`: the root check
   `self._is_directory(place.base)` runs before `with self._named():`. A refused root check
   prints a path relative to the lake (`permission denied on data1/root`). The class docstring
   says that a refusal names an absolute path. Correction: run the root check inside `_named`,
   and add a test for the absolute path and the context.
2. Small. `Provisioner._give` prints the same place two times, absolute and relative (`the CLI
   cannot give /projects/huron/helio/heliophysics the group readers: helio/heliophysics:
   Operation not permitted`). A `StorageError` that is not `PermissionDenied` still names a
   lake-relative path in the provision steps (`data1/helio/.huron-objects: File exists`).
   Correction: remove the relative path from the `_give` reason; make `_named` translate the
   path of each `StorageError`, or narrow the docstring. Update the literal assertions.
3. Small. `docs/concepts/raw-ingest.md`, the `pending_commit` row: "Until it ends" can refer to
   the collection. Correction: "Until the request ends", as in `docs/operator.md`.

Residual notes of this verification (not findings):

- `adm check` exits 8 for a share that is not mounted. Section 6.4 says 2. The test
  `test_check_needs_the_share` asserted 8 before D2.
- A temporary name of a publication that is younger than 1 hour gives no finding.
- A `.nfs*` file or a `.snapshot` directory directly in an organization directory gives no
  finding. The check reports them only below a catalog.
- An account outside the service group gets `unreadable` for each organization directory.
- The `find` line of `catalog_script` enters a `.snapshot` directory inside a catalog. D5 can
  measure whether the export lists one there.
- The duplication baseline can go down from 69 to 68.

### Diagnosis

The plan as written can be implemented. No verification found a defect in the design of D2.

- The task is too large for one implementation agent and three verifications. Old M11.9 was
  almost not built: the `unreadable` walk, `Stat.uid`, the rewrite of `check.py`, owner changes,
  `provision-catalogs`, the file mode, and six plan-4 changes. The first pass took about two
  hours and changed more than 30 files.
- Each verification found a new class of small finding in a different part of that surface.
  Each fix pass fixed its list in full. Findings 1 and 2 of verification 3 come from `_named`,
  which fix pass 2 added in its own audit.
- The STE paragraph and antecedent rules are not checked by `scripts/ste_check.py`. Each
  verifier reads the text again and finds a different sentence.
- One point of the plan was not specified: the file and format for provisioning with the API
  stopped. The implementation chose the service configuration file (`HURON_CONFIG_FILE` form)
  through `huron adm provision-orgs --config`. Two verifiers accepted this choice.

### Questions for the owner

1. Is one more fix pass and one more verification for the three small findings of
   verification 3 authorized, as for S7 of plan 2 and C1 and C3 of plan 3? This is the
   smallest way forward.
2. Path names in provisioning messages: does each failure name an absolute path, or is a
   lake-relative path allowed for an error that is not a permission refusal?
3. Is the choice for the file mode accepted (`provision-orgs --config <service configuration
   file>`, `provision-catalogs` always through the API)? D3 builds `scripts/dev-provision.py`
   on it.
4. Does `huron adm check` report a `.nfs*` file and a `.snapshot` directory directly in an
   organization directory, or only below a catalog?
5. Does this task change the exit code of `adm check` for a share that is not mounted from 8
   to 2 (section 6.4), or does that stay for a later task?

### Owner decisions (2026-11-12)

1. Two more fix and verification cycles for D2 are authorized.
2. A provisioning message can name a lake-relative path for an error that is not a permission
   refusal.
3. The file mode is accepted: `huron adm provision-orgs --config <service configuration file>`
   makes no API request, and `huron adm provision-catalogs` always uses the API.
4. `huron adm check` reports a `.nfs*` file and a `.snapshot` directory directly in an
   organization directory, as below a catalog. Only `huron adm check` reports them. No command
   at user level reports them.
5. D2 can change the exit code of `huron adm check` for a share that is not mounted, so that it
   agrees with section 6.4 of `IMPLEMENTATION_PLAN.md`.

### Verification 4 (2026-11-12): FAIL

All findings of verification 3 were fixed. Fix pass 5 addresses these findings.

1. F1, medium. A link in an organization directory or in its object area stopped the check of
   every catalog of that organization: `_organization_findings` blocked on each error finding.
2. F2, small. The `check_organization` docstring said that the check looks into the object area
   for probe files only. It also reports links and entries that it cannot stat there.
3. F3, small. The `from_file` docstring said that it refuses what the API refuses. It accepted
   `service_group: 1234`, and it does not refuse a key that occurs two times.
4. F4, small. The `stale_part` row of `docs/operator.md` named only a stopped publication. A
   stopped write of `metadata.json` also leaves a part file.
5. F5, small. Three texts said that the catalog step changes every directory. Direct mode does
   not enter a `.snapshot` or `.huron-objects` directory. The script does not skip them.
6. F6, small. A regular file named `.snapshot` directly in a catalog or namespace directory gave
   no finding.

### Verification 5 (2026-11-12): FAIL

Fix pass 5 cleared the six findings of verification 4. The verifier's `make gate` exited 0: 4455
tests passed, 24 deselected, 0 skipped; 12325 statements, 0 missed; 68 clones in 25 groups. The
work is in the working tree and is not committed. No fix pass followed.

1. Medium. `huron adm check` reports a recorded file that is on the share as `file_missing` and
   exits with code 1. The naming rule `check_rel_path` accepts `.nfsconfig` and
   `.snapshot/a.txt` as paths in a collection.
   - `_files` in `src/huron/core/storage/check.py` skips each name that `is_ignored_entry`
     matches before it looks for the record. Thus `_missing` reports a recorded `.nfs*` file.
   - No walk enters a `.snapshot` directory (`UNWALKED` in `layout.py`). Thus `_missing` reports
     a recorded file below that directory.
   - `_unnamed` in `src/huron/applications/cli/commands/context.py` hides an unrecorded user
     file named `.nfs*` from `huron status`. Its docstring says that a commit cannot record
     such a name. That is false.
   - `DirectoryWriter.remove_collection` does not enter a user `.snapshot` directory. The cause
     is the same.
   - Smallest fix: in `_files`, look for the record first and skip a `.nfs*` name only when no
     row records it. In `_missing`, do not report a recorded file below a directory that the
     walk does not enter. Apply the same rule in `_unnamed`. Add a test of each case on both
     adapters.
2. Small. The `from_file` docstring in `src/huron/applications/cli/provisioning.py` says that
   its list of checks is complete. The code accepts a key with a null value as an absent key.
   The API refuses `service_uid: null`. Smallest fix: write "when present and not null" in the
   docstring, or refuse null values, and add a test.

Residual notes, not findings:

- A marker in an organization directory that is a symbolic link, or that the check cannot read,
  gives `symbolic_link` or `unreadable`. The organization stays trusted and the check continues
  with its catalogs.
- The duplication baseline can go down from 69 to 68.

Questions for the owner:

1. Do you authorize one more fix pass and one more verification for these two findings?
2. Must the naming rule of section 3 refuse a `.snapshot` segment and a name that starts with
   `.nfs`? If it does, the check can skip these names with no record lookup. If it does not,
   the check must look for the record first.
3. Must a marker that is a symbolic link, or that the check cannot read, stop the check of the
   catalogs of that organization?

### Owner decisions after verification 5 (2026-11-12)

1. One more fix pass and one more verification for D2 are authorized.
2. The naming rule refuses a path in a collection with a segment named `.snapshot` or a segment
   that starts with `.nfs`. The refusal is `rel_path_reserved`, as for the names of Huron. This
   changes the naming rule of section 3 of `IMPLEMENTATION_PLAN.md`. No row can record such a
   name, so the check skips a `.nfs*` file and does not enter a `.snapshot` directory, with no
   look at the records. `huron add --recursive` does not stage an entry with such a name and
   gives a warning for it.
3. Huron does not support symbolic links. A marker in an organization directory that is a
   symbolic link stops the check of the catalogs of that organization. A marker that the check
   cannot read gives `unreadable`, and the check continues with the catalogs.

### Verification 6 (2026-11-12): FAIL

Fix pass 6 cleared the two findings of verification 5 and applied the owner decisions. The
verifier's `make gate` exited 0: 4487 tests passed, 24 deselected, 0 skipped; 12332 statements,
0 missed; 68 clones in 25 groups. The work is in the working tree and is not committed. No fix
pass followed.

1. Small. `tests/fakes/storage.py`, the `Subtree` docstring and `_rooted`. The docstring says
   that a link that a read meets is named by its path below `base`. Only `stat` and
   `read_bytes` translate the path. `walk`, `open_file` and `is_empty` give the path in the
   share, and `PermissionDenied` is not translated. No test asserts a wrong path. Smallest fix:
   make the docstring name `stat` and `read_bytes` only.

Residual notes, not findings:

- A directory named `.huron` in an organization directory gives `unreadable`, and the
  organization stays trusted.
- `layout.py` exports `NFS_PREFIX` and `SNAPSHOT_DIR` again after they moved to `naming.py`.
- The warning "a collection cannot have this name" can be read as the name of the collection.
  "A path in a collection cannot have this name" is clearer.

Questions for the owner:

1. Do you authorize one more fix pass and one more verification for this finding?
2. Must a directory named `.huron` in an organization directory count as a missing marker and
   stop the check of the catalogs of that organization?
3. Do you accept that `huron add --recursive` does not stage an entry named `.snapshot` or
   `.nfs*` and gives a warning, and that a named file with such a name stops the command?

### Owner decisions after verification 6 (2026-11-12)

1. One more fix pass and one more verification for D2 are authorized.
2. The owner gave no answer to question 2. A directory named `.huron` in an organization
   directory keeps its behaviour.
3. The owner gave no answer to question 3. `huron add --recursive` keeps its behaviour and the
   text of its warning.

### Verification 7 (2026-11-12): FAIL

Fix pass 7 cleared the finding of verification 6. It changed only the `Subtree` docstring and
this plan. The verifier's `make gate` exited 0: 4487 tests passed, 24 deselected, 0 skipped;
12332 statements, 0 missed; 68 clones in 25 groups. The work is in the working tree and is not
committed. No fix pass followed.

1. Small, docstring only. `src/huron/applications/cli/provisioning.py`, lines 1 to 7, the
   module docstring. It says that "the provision commands" get their input from the API or
   from the service configuration file, and that they send no request to the API in file mode.
   Only `huron adm provision-orgs` gets its input from this module and has a file mode.
   `huron adm provision-catalogs` always sends requests to the API. Smallest fix: write
   "`huron adm provision-orgs`" in the two places.

The verifier found no other defect. It wrote: "If you judge it a residual, nothing else blocks
D2."

Question for the owner:

1. Do you authorize one more fix pass and one more verification for this finding, or do you
   accept D2 with this docstring corrected and no further verification?

### Owner decisions after verification 7 (2026-11-12)

1. One more fix pass and one more verification for D2 are authorized.

## Escalation (D3, 2026-11-12)

Verification 3 of 3 failed. The workflow stopped. No fourth fix pass was made.

### State of the tree

The D3 work is in the working tree and is not committed. The tree is green. The verifier's
runs at verification 3:

- `make gate`: exit 0. 4515 tests passed, 39 deselected, 0 skipped. 12332 statements, 0
  missed. 68 clones in 25 groups against the baseline of 69 in 25.
- `uv run pytest -m integration`: 39 passed, 0 skipped.
- The web gate: `npm run check`, `npm test` (1649 passed), `npm run lint`, `npm run build` and
  `npm run test:e2e` (245 passed) all pass.
- `scripts/e2e.sh`: exit 0.
- `make demo-noaa` two times on a private stack: the two runs exit 0. The second run made no
  upload and no commit.
- `make app` itself was not run. It builds the web image again with a tag that the owner
  uses. Each part of it, but not the web, ran on a private stack.

### Verification 1 (FAIL: three findings)

1. The integration test "an overwrite over a part file left by an earlier attempt" of old
   M11.10 was missing.
2. The seed of `make app` did not go through the proxy and tusd. Old M11.10 says that a seeded
   file goes through them.
3. `tests/integration/test_cli_end_to_end.py` left its containers when the stack did not
   start.

Fix pass 2 cleared the three findings. Verification 2 confirmed this.

### Verification 2 (FAIL: one documentation finding)

1. `examples/noaa/README.md` said that the API of `make app` has no lake and no tusd. Its
   section "After `make app-reset`" said that the load uses the directories of an earlier
   load again. D3 made the two statements false.

Fix pass 3 cleared the finding. Verification 3 confirmed this.

### Verification 3 (FAIL: one documentation finding)

1. `README.md` tells the reader to run `make app-reset` and then `make app` with no step
   between them. D3 made this false in four places: line 295, lines 299 to 303, lines 346 to
   348 and line 362. A seed of `make app` now makes the catalog directories in the lake.
   `make app-reset` keeps the lake. The next seed then gets `STORAGE_FAILED`, because a create
   command adopts only an empty directory, and `make app` fails. The paragraph of D3 at lines
   305 to 310 gives the correct procedure and contradicts the four places. The verifier
   confirmed the failure and the correct procedure on a private stack. Smallest fix, text
   only: make the four places give the procedure of lines 305 to 310.

Residual notes, not findings:

- After a load stops, the catalog row stays in the database. If the reader then deletes the
  directory, the next load stops with a different error and a hint for `adm repair`.
- `docs/architecture.md` line 393 says that nginx listens on 127.0.0.1:1080 in the two stacks.
  With `make uploads`, nginx listens on each interface.

### Diagnosis

The plan is implementable. No verification found a defect in the stacks or the code after fix
pass 2. The findings of verifications 2 and 3 are of one class: D3 changed what `make app` and
`make app-reset` do, and an older text that D3 did not edit became false. The sweep of fix
pass 3 searched for terms. It did not find the four places, because the text there has none
of the terms.

### Questions for the owner

1. Do you authorize one more fix pass and one more verification for this finding?
2. `make app-reset` keeps the lake, and the next `make app` fails until the reader deletes the
   catalog directories. Is a procedure in `README.md` sufficient, or must `make app-reset`
   also empty the catalog directories of the development lake?

### Owner decisions (2026-11-12)

1. Each D task of this plan can have up to 10 verifications.
2. The owner gave no answer to question 2. So `make app-reset` keeps the lake, and `README.md`
   gives the procedure.

### Verification 4 (2026-11-12): FAIL

1. The two development stacks share one lake and keep separate databases, and no document said
   so. `make app` keeps its rows in the volume `huron-app_postgres-data`. `make up` and
   `make api` keep their rows in the volume `huron_postgres-data`. Both stacks read
   `huron.dev.yaml`, whose `lake_path` is `/data1/huron`. A seed, `make demo-noaa` or a create
   command on one stack makes catalog directories in the lake. The database of the other stack
   does not record them. A create command adopts only an empty directory. So the seed, the demo
   or a create on the other stack stops at its first catalog with `STORAGE_FAILED`. The
   verifier confirmed this with the host seed command of `web/README.md`: exit 1 with that 500.

### Defect for a later task

The verifier judged this defect outside D3. It comes from D1 (commit `a433b469`).

- `repair_hint` in `src/huron/applications/cli/errors.py` (lines 107 to 117) gives the hint "to
  make the directory again, run `huron … adm repair …`". `hint_repair` in
  `src/huron/applications/cli/commands/common.py` (line 261) applies it to `create org`,
  `create catalog` and `create namespace`. It gives the hint for each `STORAGE_FAILED`, also for
  "exists and is not an empty directory".
- A repair then adopts the directory that is not empty (`Repairer._run`,
  `src/huron/core/storage/repair.py` lines 161 to 172) and exits 0. The files that no row
  records stay in the catalog.
- Smallest fix: give no repair hint for that refusal, or make the repair refuse a directory that
  is not empty and that no row records. Add a test.

### Question for the owner (after verification 4)

1. Must `make app` and `make up` with `make api` have different default lake directories, so
   that one stack cannot stop the other?
