"""Runnable worker host. Durable extraction/publication handlers arrive in Tasks 4/6."""
import signal
import threading
from knowledge_ai.settings import Settings
from knowledge_ai.db import Database

def main():
    database = Database(Settings().database_url)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    database.engine.dispose()

if __name__ == '__main__':
    main()
