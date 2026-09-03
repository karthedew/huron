"""Products attach to a dataset or a project, matching the layer-path split.

The filesystem now scopes Gold by provenance: a product derived from exactly
one dataset lives under that dataset, a product fusing several lives under
the project (``design/layer-gold.html`` §2). ``products.dataset_id`` mirrors
that split - set for a single-source product, ``NULL`` for a fused one -
using the same nullable-attachment pattern ``snapshots.dataset_id`` already
uses. A composite foreign key on ``(dataset_id, project_id)`` pins a
single-source product's dataset to its own project, the same defense
``0001``/``0002`` already apply elsewhere: a plain ``FOREIGN KEY
(dataset_id) REFERENCES datasets(id)`` would happily accept a dataset that
belongs to a different project.

Silver is per-dataset now too, so every bronze or silver snapshot must name
a dataset; only gold may float free of one.
"""

from migrations._ddl import execute_sql

revision = "0003_layer_paths"
down_revision = "0002_rbac"
branch_labels = None
depends_on = None


DDL = r"""
ALTER TABLE datasets ADD CONSTRAINT datasets_id_project_id_unique UNIQUE (id, project_id);

ALTER TABLE products
    ADD COLUMN dataset_id uuid REFERENCES datasets(id),
    ADD CONSTRAINT products_dataset_project_fk
        FOREIGN KEY (dataset_id, project_id) REFERENCES datasets(id, project_id);

ALTER TABLE snapshots
    ADD CONSTRAINT snapshots_dataset_required_below_gold
        CHECK (layer = 'gold' OR dataset_id IS NOT NULL);
"""


def upgrade() -> None:
    """Attach products to a dataset and require one on every bronze or silver snapshot."""
    execute_sql(DDL)


def downgrade() -> None:
    """Remove the snapshot constraint, the product dataset column and its composite-key target."""
    execute_sql("""
    ALTER TABLE snapshots DROP CONSTRAINT IF EXISTS snapshots_dataset_required_below_gold;
    ALTER TABLE products
        DROP CONSTRAINT IF EXISTS products_dataset_project_fk,
        DROP COLUMN IF EXISTS dataset_id;
    ALTER TABLE datasets DROP CONSTRAINT IF EXISTS datasets_id_project_id_unique;
    """)
