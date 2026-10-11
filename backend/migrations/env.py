from alembic import context
from knowledge_ai.settings import Settings
from knowledge_ai.db import Database, Base

from knowledge_ai.profiles import models as profile_models
from knowledge_ai.ontology import models as ontology_models

database = Database(Settings().database_url)
with database.engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
