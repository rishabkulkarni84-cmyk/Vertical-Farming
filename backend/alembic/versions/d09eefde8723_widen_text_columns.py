"""widen text columns

Revision ID: d09eefde8723
Revises: 12e07e5b80da
Create Date: 2026-11-08 17:40:09.076268

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd09eefde8723'
down_revision: Union[str, Sequence[str], None] = '12e07e5b80da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('designs') as b:
        b.alter_column('strategy', existing_type=sa.String(60), type_=sa.String(200), existing_nullable=True)
    with op.batch_alter_table('market_prices') as b:
        b.alter_column('location', existing_type=sa.String(120), type_=sa.String(160), existing_nullable=True)
    with op.batch_alter_table('rooms') as b:
        b.alter_column('market_location', existing_type=sa.String(120), type_=sa.String(160), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('designs') as b:
        b.alter_column('strategy', existing_type=sa.String(200), type_=sa.String(60), existing_nullable=True)
    with op.batch_alter_table('market_prices') as b:
        b.alter_column('location', existing_type=sa.String(160), type_=sa.String(120), existing_nullable=True)
    with op.batch_alter_table('rooms') as b:
        b.alter_column('market_location', existing_type=sa.String(160), type_=sa.String(120), existing_nullable=True)
