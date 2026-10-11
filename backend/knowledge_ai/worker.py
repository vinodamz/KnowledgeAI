"""Durable extraction poller; SIGTERM stops after the bounded current call."""
import signal
import threading
from knowledge_ai.settings import Settings
from knowledge_ai.db import Database
from knowledge_ai.ingestion.jobs import run_one

def main():
    settings=Settings()
    database=Database(settings.database_url)
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    try:
        while not stop.is_set():
            try: worked=run_one(database,settings)
            except Exception: worked=False  # Lease recovery handles registry interruptions; never log raw exceptions.
            if not worked: stop.wait(2)
    finally: database.engine.dispose()

if __name__=='__main__': main()
