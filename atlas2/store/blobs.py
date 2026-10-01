"""Local content-addressed bytes with durable atomic publication."""
import hashlib
import os
from pathlib import Path
import tempfile

from atlas2.model.data import RawBlob, _digest


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class BlobStore:
    def __init__(self, root: Path):
        self.root = root
        created = not root.exists()
        root.mkdir(parents=True, exist_ok=True)
        if created:
            fsync_directory(root.parent)

    def read(self, digest: str) -> bytes:
        _digest(digest)
        data = (self.root / digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'raw blob hash mismatch: {digest}')
        return data

    def put(self, data: bytes) -> RawBlob:
        if type(data) is not bytes:
            raise TypeError('raw bytes required')
        model = RawBlob(hashlib.sha256(data).hexdigest(), len(data))
        model.validate()
        target = self.root / model.blob_sha256
        if target.exists():
            self.read(model.blob_sha256)
            return model
        fd, name = tempfile.mkstemp(prefix='.tmp-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
            fsync_directory(self.root)
        finally:
            Path(name).unlink(missing_ok=True)
        return model
