# Deploying Huron on OpenShift

`deploy/openshift` is a Kustomize base: a ConfigMap, the migration Job, the Deployment, the Service
and an edge-terminated Route. The service mounts nothing; it needs only PostgreSQL, the company OIDC
provider and the LDAP group directory.

## Rollout order

1. Build and push the image from `Containerfile` to the registry named in `kustomization.yaml`.
2. Create the secret from `secret.example.yaml` (never commit the filled copy):
   `oc apply -f secret.yaml`.
3. Set `HURON_INSTANCE_ID` in `configmap.yaml` to the UUID written into the share marker by
   `scripts/init-root.sh`, and set the issuer, company issuer and group directory URLs.
4. Run the migration: `oc apply -k deploy/openshift` creates the Job; wait for it with
   `oc wait --for=condition=complete job/huron-migrate`.
5. The Deployment starts once the Job succeeds; check `/readyz` through the Route.

For a new release, delete the finished Job (`oc delete job huron-migrate`) before applying again so
the migration runs for the new image.

## Signing-key rotation

Huron signs its tokens with ES256 keys stored in the database. A platform admin rotates with
`POST /api/v1/admin/signing-keys/rotate`; the previous key keeps verifying tokens for
`HURON_KEY_OVERLAP_HOURS` (24 by default), so rotate at least that long before retiring a key you
suspect. Replicas reload the key ring within `HURON_KEY_CACHE_SECONDS` (60 by default).
