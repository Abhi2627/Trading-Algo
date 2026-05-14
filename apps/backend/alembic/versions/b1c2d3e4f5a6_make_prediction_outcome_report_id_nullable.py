"""make prediction_outcome report_id nullable

Revision ID: b1c2d3e4f5a6
Revises: c3469cff5ee1
Create Date: 2026-05-14 09:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'c3469cff5ee1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # prediction_outcome.report_id is nullable — rows are created at signal time
    # and linked to a report later during the evening scoring task.
    op.alter_column('prediction_outcome', 'report_id', nullable=True)


def downgrade() -> None:
    op.alter_column('prediction_outcome', 'report_id', nullable=False)
