"""changing restaurant to store

Revision ID: db5ea6907421
Revises: d29fc7dc2cea
Create Date: 2026-01-29 17:32:06.602099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db5ea6907421'
down_revision: Union[str, None] = 'd29fc7dc2cea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass