from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


class BodyIter:
    def __init__(self):
        self._body = []

    def __len__(self):
        return len(self._body)

    def __iter__(self):
        return self

    def __next__(self):
        if not self._body:
            raise StopIteration
        return self._body.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._body:
            raise StopAsyncIteration
        return self._body.pop(0)

    def append(self, data: Union[Dict[str, Union[bytes, str]], bytes]):
        self._body.append(data)

    def get_body(self):
        return self._body

    def clear_body(self):
        self._body.clear()


@dataclass
class Response:
    status: Optional[int] = None
    headers: Union[List[tuple], Tuple[tuple]] = field(default_factory=list)
    body: BodyIter = field(default_factory=BodyIter)
    path: Optional[str] = b""
    stream: Optional[bool] = False
    type: Optional[str] = None

    def get_body(self):
        return self.body.get_body()

    def clear_body(self):
        self.body.clear_body()
