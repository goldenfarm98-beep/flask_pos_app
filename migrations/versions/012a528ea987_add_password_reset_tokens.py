"""Add password reset tokens

Revision ID: 012a528ea987
Revises: e6d070a8b6ac
Create Date: 2025-11-06 23:44:26.261541

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '012a528ea987'
down_revision = 'e6d070a8b6ac'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'password_reset_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token')
    )
    op.create_index(op.f('ix_password_reset_token_token'), 'password_reset_token', ['token'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_password_reset_token_token'), table_name='password_reset_token')
    op.drop_table('password_reset_token')
