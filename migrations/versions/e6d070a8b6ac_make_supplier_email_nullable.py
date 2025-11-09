"""Make supplier email nullable

Revision ID: e6d070a8b6ac
Revises: 44189b4bbd4d
Create Date: 2025-11-06 22:30:08.529968

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e6d070a8b6ac'
down_revision = '44189b4bbd4d'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    conn.execute(sa.text("""
        CREATE TABLE supplier_tmp (
            id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            address VARCHAR(200) NOT NULL,
            phone VARCHAR(50) NOT NULL,
            bank_account VARCHAR(100) NOT NULL,
            account_name VARCHAR(100) NOT NULL,
            contact_person VARCHAR(100) NOT NULL,
            email VARCHAR(120),
            website VARCHAR(200),
            PRIMARY KEY (id),
            UNIQUE (email)
        )
    """))
    conn.execute(sa.text("""
        INSERT INTO supplier_tmp (id, name, address, phone, bank_account, account_name, contact_person, email, website)
        SELECT id, name, address, phone, bank_account, account_name, contact_person, NULLIF(email, ''), website
        FROM supplier
    """))
    conn.execute(sa.text("DROP TABLE supplier"))
    conn.execute(sa.text("ALTER TABLE supplier_tmp RENAME TO supplier"))
    conn.execute(sa.text("PRAGMA foreign_keys=ON"))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    conn.execute(sa.text("""
        CREATE TABLE supplier_tmp (
            id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            address VARCHAR(200) NOT NULL,
            phone VARCHAR(50) NOT NULL,
            bank_account VARCHAR(100) NOT NULL,
            account_name VARCHAR(100) NOT NULL,
            contact_person VARCHAR(100) NOT NULL,
            email VARCHAR(120) NOT NULL,
            website VARCHAR(200),
            PRIMARY KEY (id),
            UNIQUE (email)
        )
    """))
    conn.execute(sa.text("""
        INSERT INTO supplier_tmp (id, name, address, phone, bank_account, account_name, contact_person, email, website)
        SELECT id, name, address, phone, bank_account, account_name, contact_person, COALESCE(email, ''), website
        FROM supplier
    """))
    conn.execute(sa.text("DROP TABLE supplier"))
    conn.execute(sa.text("ALTER TABLE supplier_tmp RENAME TO supplier"))
    conn.execute(sa.text("PRAGMA foreign_keys=ON"))
