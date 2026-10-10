"""baseline schema: documents, audit_log, doc_store

Idempotent on purpose: environments created by the app's startup `create_all` already have these tables, so the
baseline only creates what is missing (`checkfirst`). Later revisions should be normal incremental migrations.
"""
from alembic import op

from app.infra.orm import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("baseline is not reversible (would drop all data); restore from backup instead")
