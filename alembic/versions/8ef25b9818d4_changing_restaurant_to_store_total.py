"""changing restaurant to store - total

Revision ID: 8ef25b9818d4
Revises: 9c844c6d5950
Create Date: 2026-01-29 18:49:08.241830

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ef25b9818d4'
down_revision: Union[str, None] = '9c844c6d5950'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass