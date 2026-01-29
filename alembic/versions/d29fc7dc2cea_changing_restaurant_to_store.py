"""changing restaurant to store

Revision ID: d29fc7dc2cea
Revises: 628063d40f37
Create Date: 2026-01-29 17:31:43.474022

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd29fc7dc2cea'
down_revision: Union[str, None] = '628063d40f37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass