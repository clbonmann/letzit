"""changing restaurant to store

Revision ID: 36eeb7d35d73
Revises: db5ea6907421
Create Date: 2026-01-29 17:32:39.245806

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36eeb7d35d73'
down_revision: Union[str, None] = 'db5ea6907421'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass