# D0 deletion matrix

Every declared method/property on the four old symbols is inventoried. D0 deleted nothing; rows explicitly closed below were migrated and verified in D1. Consumer/test families are detailed in [consumer-map.md](consumer-map.md); exact references including typing and aliases are in [consumer-references.txt](consumer-references.txt). Update migrated callers and close only after the old implementation is removed.

| Old symbol | Baseline location | Intended owner | Migrated callers | Status |
| --- | --- | --- | --- | --- |
| `CatalogService.__init__` | `src/huron/core/catalog.py:38` | D1–D4 application composition of focused authorized workflows | None (baseline) | Open |
| `CatalogService.create_organization` | `src/huron/core/catalog.py:48` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `CatalogService.patch_organization` | `src/huron/core/catalog.py:70` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `CatalogService.create_project` | `src/huron/core/catalog.py:101` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `CatalogService.patch_project` | `src/huron/core/catalog.py:138` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `CatalogService.create_dataset` | `src/huron/core/catalog.py:169` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `CatalogService.patch_dataset` | `src/huron/core/catalog.py:212` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `CatalogService.create_release` | `src/huron/core/catalog.py:243` | D3b releases and release persistence | None (baseline) | Open |
| `CatalogService.organization` | `src/huron/core/catalog.py:281` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `CatalogService.project` | `src/huron/core/catalog.py:292` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `CatalogService.dataset` | `src/huron/core/catalog.py:303` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `CatalogService.release` | `src/huron/core/catalog.py:314` | D3b releases and release persistence | None (baseline) | Open |
| `CatalogService.organizations` | `src/huron/core/catalog.py:326` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `CatalogService.projects` | `src/huron/core/catalog.py:342` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `CatalogService.datasets` | `src/huron/core/catalog.py:359` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `CatalogService.releases` | `src/huron/core/catalog.py:376` | D3b releases and release persistence | None (baseline) | Open |
| `CatalogService.grant_role` | `src/huron/core/catalog.py:393` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.revoke_role` | `src/huron/core/catalog.py:427` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.get_role_binding` | `src/huron/core/catalog.py:442` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.bindings_at` | `src/huron/core/catalog.py:457` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.create_service_account` | `src/huron/core/catalog.py:472` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.get_service_account` | `src/huron/core/catalog.py:493` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.list_service_accounts` | `src/huron/core/catalog.py:508` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.disable_service_account` | `src/huron/core/catalog.py:522` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.create_policy` | `src/huron/core/catalog.py:540` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.attach_policy` | `src/huron/core/catalog.py:559` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `CatalogService.list_policies` | `src/huron/core/catalog.py:581` | D4 policies workflow | None (baseline) | Open |
| `CatalogService.layers` | `src/huron/core/catalog.py:589` | D4 authorized dataset-layer discovery using catalog collections and existing layer rules | None (baseline) | Open |
| `HierarchyRepository.__init__` | `src/huron/core/_catalog.py:96` | D4 application startup initializes Raw storage; concrete collaborators injected into focused workflows | None (baseline) | Open |
| `HierarchyRepository.data_root` | `src/huron/core/_catalog.py:127` | D4 application/runtime Raw storage capability | None (baseline) | Open |
| `HierarchyRepository._claimed_result` | `src/huron/core/_catalog.py:138` | D3a/D3b creation/release idempotency mechanics | None (baseline) | Open |
| `HierarchyRepository.create_organization` | `src/huron/core/_catalog.py:163` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `HierarchyRepository.patch_organization` | `src/huron/core/_catalog.py:203` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyRepository.create_project` | `src/huron/core/_catalog.py:248` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `HierarchyRepository.patch_project` | `src/huron/core/_catalog.py:325` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyRepository.create_dataset` | `src/huron/core/_catalog.py:365` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `HierarchyRepository.patch_dataset` | `src/huron/core/_catalog.py:451` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyRepository._patch_description` | `src/huron/core/_catalog.py:490` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyRepository._update_description` | `src/huron/core/_catalog.py:525` | D2 described collection CAS persistence | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyRepository.create_release` | `src/huron/core/_catalog.py:555` | D3b releases and release persistence | None (baseline) | Open |
| `HierarchyRepository.organization` | `src/huron/core/_catalog.py:636` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.project` | `src/huron/core/_catalog.py:650` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.dataset` | `src/huron/core/_catalog.py:664` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.release` | `src/huron/core/_catalog.py:678` | D3b releases and release persistence | None (baseline) | Open |
| `HierarchyRepository.organizations` | `src/huron/core/_catalog.py:693` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.projects` | `src/huron/core/_catalog.py:711` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.datasets` | `src/huron/core/_catalog.py:740` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.releases` | `src/huron/core/_catalog.py:768` | D3b releases and release persistence | None (baseline) | Open |
| `HierarchyRepository.project_visibilities` | `src/huron/core/_catalog.py:790` | D1 access/scope focused facts | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.dataset_parents` | `src/huron/core/_catalog.py:801` | D1 access/scope focused facts | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.grant_role` | `src/huron/core/_catalog.py:824` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.revoke_role` | `src/huron/core/_catalog.py:869` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.get_role_binding` | `src/huron/core/_catalog.py:883` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.bindings_for` | `src/huron/core/_catalog.py:896` | D1 access/scope focused facts | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.bindings_at` | `src/huron/core/_catalog.py:915` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.create_service_account` | `src/huron/core/_catalog.py:937` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.get_service_account` | `src/huron/core/_catalog.py:973` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.service_account_by_subject` | `src/huron/core/_catalog.py:986` | D1 access/scope focused facts | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyRepository.list_service_accounts` | `src/huron/core/_catalog.py:1002` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.disable_service_account` | `src/huron/core/_catalog.py:1018` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.create_policy` | `src/huron/core/_catalog.py:1043` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.attach_policy` | `src/huron/core/_catalog.py:1065` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository.list_policies` | `src/huron/core/_catalog.py:1091` | D4 policies workflow with RBAC storage | None (baseline) | Open |
| `HierarchyRepository._require_scope` | `src/huron/core/_catalog.py:1102` | D4 bindings/policies/service_accounts; focused RBAC ports | None (baseline) | Open |
| `HierarchyRepository._write_generation` | `src/huron/core/_catalog.py:1141` | D2/D3 workflow generation publication through injected Raw storage | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyWriter.claim` | `src/huron/core/ports.py:373` | D3 creation/release claim port and D4 Raw atomic claim port; same transaction connection | None (baseline) | Open |
| `HierarchyWriter.remember` | `src/huron/core/ports.py:397` | D3 creation/release receipt port and D4 Raw atomic receipt port; same transaction connection | None (baseline) | Open |
| `HierarchyWriter.insert_organization` | `src/huron/core/ports.py:414` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `HierarchyWriter.insert_project` | `src/huron/core/ports.py:426` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `HierarchyWriter.insert_dataset` | `src/huron/core/ports.py:437` | D3a catalog_creation and creation writer | None (baseline) | Open |
| `HierarchyWriter.insert_release` | `src/huron/core/ports.py:452` | D3b releases and release persistence | None (baseline) | Open |
| `HierarchyWriter.update_organization` | `src/huron/core/ports.py:467` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyWriter.update_project` | `src/huron/core/ports.py:483` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyWriter.update_dataset` | `src/huron/core/ports.py:499` | D2 described collections and CAS writers | D2 typed collections, CAS adapters, HTTP and retained behavioral tests | Closed in D2 |
| `HierarchyWriter.insert_revision` | `src/huron/core/ports.py:515` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.insert_audit_event` | `src/huron/core/ports.py:525` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.insert_outbox_event` | `src/huron/core/ports.py:533` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.lock_ingest_session` | `src/huron/core/ports.py:541` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.freeze_commit` | `src/huron/core/ports.py:552` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.begin_ingest` | `src/huron/core/ports.py:571` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.update_ingest_session` | `src/huron/core/ports.py:608` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.renew_ingest_session` | `src/huron/core/ports.py:625` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.expire_ingest_session` | `src/huron/core/ports.py:640` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyWriter.update_ingest_file` | `src/huron/core/ports.py:662` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyStore.transaction` | `src/huron/core/ports.py:699` | D2/D3/D4 consumer-owned catalog/Raw atomic transaction ports | None (baseline) | Open |
| `HierarchyStore.organization` | `src/huron/core/ports.py:712` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyStore.project` | `src/huron/core/ports.py:724` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyStore.dataset` | `src/huron/core/ports.py:736` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyStore.release` | `src/huron/core/ports.py:748` | D3b releases and release persistence | None (baseline) | Open |
| `HierarchyStore.revision_ref` | `src/huron/core/ports.py:761` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyStore.organizations` | `src/huron/core/ports.py:778` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyStore.projects` | `src/huron/core/ports.py:796` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyStore.datasets` | `src/huron/core/ports.py:820` | D1 catalog_collections/catalog_ports and adapter typed reads | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyStore.releases` | `src/huron/core/ports.py:844` | D3b releases and release persistence | None (baseline) | Open |
| `HierarchyStore.project_visibilities` | `src/huron/core/ports.py:863` | D1 access/scope focused facts | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyStore.dataset_parents` | `src/huron/core/ports.py:875` | D1 access/scope focused facts | D1 core/internal Raw/revision, API guards/wiring, memory/PostgreSQL and retained tests | Closed in D1 |
| `HierarchyStore.revision` | `src/huron/core/ports.py:892` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyStore.latest_committed_revision` | `src/huron/core/ports.py:907` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyStore.ingest_session` | `src/huron/core/ports.py:921` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyStore.ingest_files` | `src/huron/core/ports.py:934` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyStore.ingest_file` | `src/huron/core/ports.py:946` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
| `HierarchyStore.lapsed_ingest_sessions` | `src/huron/core/ports.py:959` | D4/D6 Raw/revision consumer ports; preserve atomic writer | None (baseline) | Open |
