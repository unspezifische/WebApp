"""add sound duration

Revision ID: d4a91c6e7b20
Revises: c7f1a4d9e2b6
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4a91c6e7b20'
down_revision = 'c7f1a4d9e2b6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sound_asset', sa.Column('duration_seconds', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('sound_asset', 'duration_seconds')
