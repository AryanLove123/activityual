"""SQLAlchemy Core definition of auth_schema.app_user."""

import sqlalchemy as sa

metadata = sa.MetaData()

app_user = sa.Table(
    "app_user",
    metadata,
    sa.Column(
        "id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
    ),
    sa.Column("email", sa.Text, nullable=False),
    sa.Column("password_hash", sa.Text, nullable=False),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    schema="auth_schema",
)
