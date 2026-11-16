import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

metadata = sa.MetaData()

activity = sa.Table(
    "activity", metadata,
    sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("user_id", sa.Uuid, nullable=False),
    sa.Column("title", sa.String(100), nullable=False),
    sa.Column("category", sa.String(50), nullable=False, server_default="general"),
    sa.Column("notes", sa.String(1000), nullable=False, server_default=""),
    sa.Column("frequency_type", sa.Text, nullable=False),
    sa.Column("days_of_week", ARRAY(sa.SmallInteger), nullable=False),
    sa.Column("timezone", sa.Text, nullable=False),
    sa.Column("start_date", sa.Date, nullable=False),
    sa.Column("end_date", sa.Date),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("schedule_revision", sa.Integer, nullable=False, server_default="1"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    schema="activity_schema",
)
