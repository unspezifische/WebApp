"""separate D&D campaign system and ruleset

Revision ID: 93d7e5a1b2c4
Revises: 81e4c7a2d9f0
"""

from alembic import op
import sqlalchemy as sa


revision = '93d7e5a1b2c4'
down_revision = '81e4c7a2d9f0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('campaign', sa.Column('ruleset', sa.String(length=30), nullable=True))
    op.execute("""
        UPDATE campaign
        SET ruleset = CASE
                WHEN system = 'D&D 3.5e' THEN '3.5e'
                WHEN system = 'D&D 4e' THEN '4e'
                WHEN system = 'D&D 5e (2024)' THEN '5e (2024)'
                ELSE '5e'
            END,
            system = 'D&D'
        WHERE system IN ('D&D', 'D&D 3.5e', 'D&D 4e', 'D&D 5e', 'D&D 5e (2024)')
    """)


def downgrade():
    op.execute("""
        UPDATE campaign
        SET system = CASE ruleset
                WHEN '3.5e' THEN 'D&D 3.5e'
                WHEN '4e' THEN 'D&D 4e'
                WHEN '5e (2024)' THEN 'D&D 5e (2024)'
                ELSE 'D&D 5e'
            END
        WHERE system = 'D&D'
    """)
    op.drop_column('campaign', 'ruleset')
