"""add_signal_outcome_table

Revision ID: c3469cff5ee1
Revises: a6fa19d4d7de
Create Date: 2026-05-12 17:50:09.234844

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3469cff5ee1'
down_revision: Union[str, Sequence[str], None] = 'a6fa19d4d7de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # signal_outcome table was created manually via SQL during initial deploy.
    # This migration is a no-op that stamps the revision so Alembic tracks it.
    # The table already exists with correct schema — no DDL changes needed.
    pass


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('signal_outcome')
