"""Durable extraction poller; SIGTERM stops after the bounded current call."""
import logging
import signal
from sqlalchemy.exc import SQLAlchemyError
import threading
from knowledge_ai.settings import Settings
from knowledge_ai.db import Database
from knowledge_ai.ingestion.jobs import run_one

logger=logging.getLogger(__name__)

def poll_once(database,settings):
    try:
        return run_one(database,settings)
    except Exception as error:
        category='registry_failure' if isinstance(error,SQLAlchemyError) else 'worker_failure'
        # Never include exception text, traceback, request bodies, source data or keys.
        logger.error('worker_poll_failed category=%s',category)
        return False

def main():
    settings=Settings()
    database=Database(settings.database_url)
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    try:
        while not stop.is_set():
            worked=poll_once(database,settings)
            if not worked: stop.wait(2)
    finally: database.engine.dispose()

if __name__=='__main__': main()
