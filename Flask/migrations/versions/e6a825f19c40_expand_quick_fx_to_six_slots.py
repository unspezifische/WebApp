"""expand Quick FX to six slots

Revision ID: e6a825f19c40
Revises: d4a91c6e7b20
"""

from alembic import op


revision = 'e6a825f19c40'
down_revision = 'd4a91c6e7b20'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        'ck_sound_quick_effect_slot_range',
        'sound_quick_effect_slot',
        type_='check',
    )
    op.create_check_constraint(
        'ck_sound_quick_effect_slot_range',
        'sound_quick_effect_slot',
        'slot >= 1 AND slot <= 6',
    )


def downgrade():
    op.execute('DELETE FROM sound_quick_effect_slot WHERE slot = 6')
    op.drop_constraint(
        'ck_sound_quick_effect_slot_range',
        'sound_quick_effect_slot',
        type_='check',
    )
    op.create_check_constraint(
        'ck_sound_quick_effect_slot_range',
        'sound_quick_effect_slot',
        'slot >= 1 AND slot <= 5',
    )
