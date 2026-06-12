"""add staff_shifts table and is_on_shift column to users

Revision ID: c50fd7b21859
Revises: 3f666a538756
Create Date: 2025-09-11 07:53:23.222488

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c50fd7b21859'
down_revision = '3f666a538756'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 0) Temizlik: yarım kalan batch alter’dan kalmış olabilir
    try:
        bind.exec_driver_sql("DROP TABLE IF EXISTS _alembic_tmp_users;")
    except Exception:
        pass

    # 1) users tablosuna is_on_shift (SQLite-safe ekleme)
    user_cols = [c['name'] for c in inspector.get_columns('users')]
    if 'is_on_shift' not in user_cols:
        # SQLite'ta NOT NULL + DEFAULT ile tek adımda eklemek güvenli
        op.execute("ALTER TABLE users ADD COLUMN is_on_shift INTEGER NOT NULL DEFAULT 0")

    # 2) staff_shifts tablosu (guard ile)
    if 'staff_shifts' not in inspector.get_table_names():
        op.create_table(
            'staff_shifts',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
            sa.Column('start_at', sa.DateTime(), nullable=True),
            sa.Column('end_at', sa.DateTime(), nullable=True),
        )
        op.create_index(op.f('ix_staff_shifts_user_id'), 'staff_shifts', ['user_id'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # staff_shifts'i sil
    if 'staff_shifts' in inspector.get_table_names():
        op.drop_index(op.f('ix_staff_shifts_user_id'), table_name='staff_shifts')
        op.drop_table('staff_shifts')

    # users.is_on_shift'i kaldır (SQLite'ta sütun düşürmek zordur; genelde bırakılır)
    # Eğer zorunluysa, yeni tablo yaratıp kopyalama yapılmalı. Basit senaryo için geçiyoruz.
    try:
        bind.exec_driver_sql("ALTER TABLE users DROP COLUMN is_on_shift;")
    except Exception:
        pass  # SQLite desteklemez; prod için ayrı yeniden-yaratma senaryosu gerekir