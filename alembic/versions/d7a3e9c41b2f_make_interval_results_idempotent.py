"""Make interval_results idempotent: one row per (job_id, timestamp), plus notified_at

Revision ID: d7a3e9c41b2f
Revises: 2491a531b839
Create Date: 2026-10-29 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a3e9c41b2f'
down_revision: Union[str, None] = '2491a531b839'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interval_results', sa.Column('notified_at', sa.DateTime(), nullable=True))

    # Rows written before this migration were already emailed.
    op.execute("UPDATE interval_results SET notified_at = timestamp")

    # Drop duplicates left by earlier redeliveries (keep one row per interval)
    # so the unique constraint can be created.
    op.execute(
        """
        DELETE FROM interval_results a
        USING interval_results b
        WHERE a.job_id = b.job_id
          AND a.timestamp = b.timestamp
          AND a.id::text > b.id::text
        """
    )

    op.create_unique_constraint(
        'uq_interval_results_job_timestamp', 'interval_results', ['job_id', 'timestamp']
    )


def downgrade() -> None:
    op.drop_constraint('uq_interval_results_job_timestamp', 'interval_results', type_='unique')
    op.drop_column('interval_results', 'notified_at')
