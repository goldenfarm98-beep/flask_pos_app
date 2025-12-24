"""MySQL baseline (no-op)"""

from alembic import op
import sqlalchemy as sa

# Alembic identifiers
revision = '0001_mysql_baseline'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # This is a baseline marker; treat current DB schema as-is.
    pass

def downgrade():
    pass
