"""store map media and world atlas in postgres

Revision ID: b4e8c2d1f6a9
Revises: 93d7e5a1b2c4
"""

from alembic import op
import sqlalchemy as sa


revision = 'b4e8c2d1f6a9'
down_revision = '93d7e5a1b2c4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'map_media_asset',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('public_id', sa.String(length=32), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('purpose', sa.String(length=40), nullable=False, server_default='map_reference'),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('mimetype', sa.String(length=100), nullable=False),
        sa.Column('byte_size', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('pixel_width', sa.Integer()),
        sa.Column('pixel_height', sa.Integer()),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaign.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_map_media_asset_public_id', 'map_media_asset', ['public_id'], unique=True)
    op.create_index('ix_map_media_asset_campaign_id', 'map_media_asset', ['campaign_id'])
    op.create_table(
        'campaign_world_atlas',
        sa.Column('campaign_id', sa.Integer(), primary_key=True),
        sa.Column('setting_key', sa.String(length=80), nullable=False, server_default='custom'),
        sa.Column('coordinate_space_key', sa.String(length=80), nullable=False, server_default='custom-v1'),
        sa.Column('name', sa.String(length=160), nullable=False, server_default='Campaign World'),
        sa.Column('image_asset_id', sa.Integer()),
        sa.Column('attribution', sa.Text()),
        sa.Column('source_name', sa.String(length=255)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaign.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['image_asset_id'], ['map_media_asset.id'], ondelete='SET NULL'),
    )
    op.create_table(
        'setting_world_atlas',
        sa.Column('setting_key', sa.String(length=80), primary_key=True),
        sa.Column('coordinate_space_key', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('image_asset_id', sa.Integer()),
        sa.Column('attribution', sa.Text()),
        sa.Column('source_name', sa.String(length=255)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['image_asset_id'], ['map_media_asset.id'], ondelete='SET NULL'),
    )


def downgrade():
    op.drop_table('setting_world_atlas')
    op.drop_table('campaign_world_atlas')
    op.drop_index('ix_map_media_asset_campaign_id', table_name='map_media_asset')
    op.drop_index('ix_map_media_asset_public_id', table_name='map_media_asset')
    op.drop_table('map_media_asset')
