"""add embedded sound cover art

Revision ID: c7f1a4d9e2b6
Revises: b4e8c2d1f6a9
"""

from alembic import op
import sqlalchemy as sa


revision = 'c7f1a4d9e2b6'
down_revision = 'b4e8c2d1f6a9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sound_asset', sa.Column('cover_filename', sa.String(length=255)))
    op.add_column('sound_asset', sa.Column('cover_mimetype', sa.String(length=100)))


def downgrade():
    op.drop_column('sound_asset', 'cover_mimetype')
    op.drop_column('sound_asset', 'cover_filename')
