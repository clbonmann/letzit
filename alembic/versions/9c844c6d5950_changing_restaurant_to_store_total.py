"""changing restaurant to store - total

Revision ID: 9c844c6d5950
Revises: 67177f1b59ac
Create Date: 2026-01-29 18:47:44.079593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c844c6d5950'
down_revision: Union[str, None] = '67177f1b59ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass