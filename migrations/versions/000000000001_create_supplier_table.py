"""create supplier table (earliest)"""

from alembic import op
import sqlalchemy as sa

revision = '000000000001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'supplier',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('nama', sa.String(length=100), nullable=False),
        sa.Column('alamat', sa.String(length=255), nullable=True),
        sa.Column('telepon', sa.String(length=50), nullable=True),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )

def downgrade():
    op.execute("DROP TABLE IF EXISTS supplier")
