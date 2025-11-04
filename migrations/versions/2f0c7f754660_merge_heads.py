"""merge heads

Revision ID: 2f0c7f754660
Revises: 0001_mysql_baseline, c15aa1f8aae1
Create Date: 2025-11-03 19:36:33.388325

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2f0c7f754660'
down_revision = ('0001_mysql_baseline', 'c15aa1f8aae1')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
