"""Entry layers, invariant N, and the ingest_pipeline role.

Three changes, one decision: a dataset may enter the lake above raw.

``datasets.entry_layer`` records where a dataset's data first arrives. The
default is ``raw`` and that stays the common case, but a dataset fed by a
streaming source or holding published reference data enters at ``bronze`` or
``silver`` and has no raw revision and no bronze snapshot - not yet, but
ever. Gold is excluded by CHECK: every product version carries a derivation
record (invariant K), so "gold with no inputs" is not a product.

``snapshots.provenance`` gains the constraint that makes invariant N
enforceable rather than aspirational: every snapshot states one of three
origins - ``promotion`` (descends from a lower layer here), ``external`` (a
lineage root; the source is outside Huron's custody), or ``derivation`` (a
Gold product version's record) - and a gold snapshot may only ever state
``derivation``. The full shape is validated in Python against
``huron.schema`` documents/snapshot-provenance-v1.json; the database keeps
the part that a bad writer must not be able to bypass.

``ingest_pipeline`` is the role a direct-entry pipeline needs: plain
``pipeline`` writes datasets that already exist, and a feed arriving from
outside has to create the dataset it is about to fill. It binds at project
scope only, and to service accounts only - so silver/gold writes remain
service-account-only, which is the real invariant the role model enforces.
"""

from alembic import op

revision = "0004_entry_layers"
down_revision = "0003_layer_paths"
branch_labels = None
depends_on = None


DDL = r"""
ALTER TABLE datasets
    ADD COLUMN entry_layer text NOT NULL DEFAULT 'raw'
        CHECK (entry_layer IN ('raw', 'bronze', 'silver'));

-- Both CHECKs are written NULL-safe on purpose. A CHECK passes on NULL, so
-- the obvious spelling (`provenance->>'kind' IN (...)`) would wave through
-- exactly the row this constraint exists to stop: provenance '{}', which
-- states no origin at all. Verified: the naive form accepted it.
ALTER TABLE snapshots
    ADD CONSTRAINT snapshots_provenance_states_an_origin
        CHECK (provenance->>'kind' IS NOT NULL
               AND provenance->>'kind' IN ('promotion', 'external', 'derivation')),
    ADD CONSTRAINT snapshots_gold_is_never_an_entry_layer
        CHECK (layer <> 'gold'
               OR provenance->>'kind' IS NOT DISTINCT FROM 'derivation');

INSERT INTO roles (code, title, description, allowed_principal_kinds, bindable_scopes) VALUES
    ('ingest_pipeline', 'Ingest Pipeline',
     'Creates the datasets it fills; for sources outside the lake. Service accounts only.',
     ARRAY['service_account'], ARRAY['PROJECT']);

INSERT INTO role_capabilities (role_code, capability_code, layers) VALUES
    ('ingest_pipeline', 'dataset.discover', NULL),
    ('ingest_pipeline', 'dataset.create',   NULL),
    ('ingest_pipeline', 'data.read',        NULL),
    ('ingest_pipeline', 'data.write',       ARRAY['bronze','silver','gold']);

UPDATE roles
   SET description = 'Writes bronze, silver and gold for datasets that already exist. '
                     'Service accounts only.'
 WHERE code = 'pipeline';
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
    UPDATE roles
       SET description = 'The only role that writes silver and gold. Service accounts only.'
     WHERE code = 'pipeline';
    DELETE FROM role_bindings WHERE role_code = 'ingest_pipeline';
    DELETE FROM role_capabilities WHERE role_code = 'ingest_pipeline';
    DELETE FROM roles WHERE code = 'ingest_pipeline';
    ALTER TABLE snapshots
        DROP CONSTRAINT IF EXISTS snapshots_gold_is_never_an_entry_layer,
        DROP CONSTRAINT IF EXISTS snapshots_provenance_states_an_origin;
    ALTER TABLE datasets DROP COLUMN IF EXISTS entry_layer;
    """)
