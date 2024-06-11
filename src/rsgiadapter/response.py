import warnings
from dataclasses import dataclass, field
from tempfile import SpooledTemporaryFile
from typing import List, Optional, Tuple, Union


class BodyManager:
    """
    A body iterator that can be used to iterate over the body in chunks.
    Supports both synchronous and asynchronous iteration.
    Instance support reuse, but not suggested.
    Yields:
        Chunks of the body.
    Args:
        chunk_size: The size of the chunks to be returned.

    Returns:
        A generator that yields chunks of the body.
    """

    def __init__(self, chunk_size: int = 1024 * 1024):
        self.chunk_size = chunk_size
        self._body_length = 0
        self._body = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")

    @property
    def closed(self) -> bool:
        return self._body.closed

    def __len__(self):
        return self._body_length

    def __iter__(self):
        self._body.seek(0)  # Ensure iteration starts from the beginning
        return self

    def __next__(self):
        chunk = self._body.read(self.chunk_size)
        if not chunk:
            raise StopIteration
        return chunk

    def __aiter__(self):
        self._body.seek(0)
        return self

    async def __anext__(self):
        chunk = self._body.read(self.chunk_size)
        if not chunk:
            raise StopAsyncIteration
        return chunk

    def __del__(self):
        try:
            if not self.closed:
                self._body.close()
        except Exception:
            pass  # Suppress exceptions during garbage collection

    def append(self, data: Union[bytes, str]):
        if not isinstance(data, (str, bytes)):
            warnings.warn(
                "Adapter body manager received not supported body",
                ResourceWarning,
                stacklevel=2,
                source=self,
            )
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._body.write(data)
        self._body_length += 1
        if self._body_length == 1:
            self.chunk_size = len(data) or self.chunk_size

    def get_body(self) -> bytes:
        if not self._body.closed:
            self._body.seek(0)
            return self._body.read()
        return b""

    def clear_body(self):
        if not self.closed:
            self._body.close()
        self._body = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
        self._body_length = 0


@dataclass
class Response:
    status: Optional[int] = None
    headers: Union[List[tuple], Tuple[tuple]] = field(default_factory=list)
    body: BodyManager = field(default_factory=BodyManager)
    path: Optional[str] = b""
    stream: Optional[bool] = False
    type: Optional[str] = None

    def get_body(self) -> bytes:
        return self.body.get_body()

    def clear_body(self):
        self.body.clear_body()
