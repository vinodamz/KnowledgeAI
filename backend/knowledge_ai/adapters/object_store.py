"""Content addressed immutable local objects; filenames never become paths."""
import hashlib
import os
import tempfile
from pathlib import Path

class ObjectStore:
    def __init__(self, directory): self.root=Path(directory)
    def put(self, content: bytes) -> str:
        key=hashlib.sha256(content).hexdigest()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.root/key
        fd,temporary=tempfile.mkstemp(prefix='.upload-',dir=self.root)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(content);stream.flush();os.fsync(stream.fileno())
            try: os.link(temporary,path)
            except FileExistsError:
                if path.read_bytes()!=content: raise ValueError('Object integrity failure')
            directory_fd=os.open(self.root,os.O_RDONLY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
        finally: Path(temporary).unlink(missing_ok=True)
        return key
    def get(self,key):
        if len(key)!=64 or any(c not in '0123456789abcdef' for c in key): raise ValueError('Invalid object key')
        content=(self.root/key).read_bytes()
        if hashlib.sha256(content).hexdigest()!=key: raise ValueError('Object integrity failure')
        return content
