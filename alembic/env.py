from alembic import context
from app.db import Base, settings, make_engine, UTCDateTime
from app import models

target_metadata = Base.metadata

def render_item(kind, obj, autogen_context):
    if kind == 'type' and isinstance(obj, UTCDateTime):
        return 'sa.DateTime(timezone=True)'
    return False
if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True, compare_type=True, render_item=render_item)
    with context.begin_transaction():
        context.run_migrations()
else:
    with make_engine(settings.database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, render_item=render_item)
        with context.begin_transaction():
            context.run_migrations()
