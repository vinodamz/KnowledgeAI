"""Export schema without reading deployment secrets or opening a database."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from knowledge_ai.app import create_app
from knowledge_ai.settings import Settings
app=create_app(Settings(database_url='postgresql+psycopg://unused:unused@localhost/unused',signing_secret='schema-export-only-not-a-runtime-secret'))
Path('openapi.json').write_text(json.dumps(app.openapi(),indent=2)+'\n')

