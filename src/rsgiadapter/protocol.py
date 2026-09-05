"""
Type templates for the ASGI scopes built by the adapter and the RSGI
scope/protocol objects handed over by RSGI servers (e.g. granian).

The ``RSGI*`` classes are never instantiated at runtime: they exist only as
structural templates for type checking, since the real objects are provided
by the RSGI server. Their attribute sets mirror the RSGI spec
(https://github.com/emmett-framework/granian/blob/master/docs/spec/RSGI.md).
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple, TypedDict, Union


class ASGIScope(TypedDict):
    asgi: Dict[str, str]
    extensions: Dict[str, Dict[str, Any]]
    type: str
    http_version: str
    server: Iterable[Union[str, int, None]]
    client: Iterable[Union[str, int, None]]
    scheme: str
    method: str
    path: str
    raw_path: bytes
    query_string: bytes
    headers: Iterable[Tuple[Union[str, bytes], Union[str, bytes]]]
    root_path: str
    state: Optional[Dict[str, Any]]


class RSGIHTTPScope(object):
    """RSGI HTTP Scope template, for type hinting"""

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def __new__(cls, *args, **kwargs):
        pass

    authority = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    client = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    headers = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    http_version = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    method = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    path = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    proto = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    query_string = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    rsgi_version = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    scheme = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default

    server = property(
        lambda self: object(), lambda self, v: None, lambda self: None
    )  # default


class RSGIHTTPStreamTransport(object):
    """RSGI stream response transport template, for type hinting"""

    async def send_bytes(self, data: bytes) -> None:
        ...

    async def send_str(self, data: str) -> None:
        ...


class RSGIHTTPProtocol(object):
    """RSGI HTTP Protocol template, for type hinting"""

    proto: str
    http_version: str
    rsgi_version: str
    server: str
    client: str
    scheme: str
    method: str
    path: str
    query_string: str
    headers: List
    body: bytes

    def response_bytes(self, *args, **kwargs) -> None:
        ...

    def response_empty(self, *args, **kwargs) -> None:
        ...

    def response_file(self, *args, **kwargs) -> None:
        ...

    def response_str(self, *args, **kwargs) -> None:
        ...

    def response_stream(
        self, *args, **kwargs
    ) -> RSGIHTTPStreamTransport:
        ...

    def __aiter__(self, *args, **kwargs):
        return self

    async def __anext__(self, *args, **kwargs):
        if self.data:
            return self.data.pop(0)
        raise StopAsyncIteration

    def __call__(self, *args, **kwargs) -> bytes:
        ...

    def __init__(self, *args, **kwargs):
        self.data = list(args)

    @staticmethod
    def __new__(cls, *args, **kwargs):
        ...


class RSGIWebsocketMessage:
    """
    Incoming websocket message template, for type hinting.

    kind: 0 = closed by client, 1 = bytes message, 2 = string message
    data: message content, absent for the close message
    """

    kind: int
    data: Optional[Union[bytes, str]]


class RSGIWebsocketTransport(object):
    """RSGI Websocket transport template, for type hinting"""

    async def receive(self, *args, **kwargs) -> RSGIWebsocketMessage:
        ...

    async def send_bytes(self, data: bytes) -> None:
        ...

    async def send_str(self, data: str) -> None:
        ...


class RSGIWebsocketProtocol(object):
    """RSGI Websocket protocol template, for type hinting

    ``accept`` completes the handshake and returns the transport;
    ``close(status)`` ends the connection - before acceptance ``status`` is
    emitted as the HTTP status of a denial response, after acceptance it is
    used as the websocket close code.
    """

    async def accept(self, *args, **kwargs) -> "RSGIWebsocketTransport":
        ...

    def close(self, status: Optional[int] = None):
        ...

    def __init__(self, *args, **kwargs):
        ...

    @staticmethod
    def __new__(cls, *args, **kwargs):
        ...


class RSGIWebsocketScope(RSGIHTTPScope):
    """RSGI Websocket scope template, for type hinting"""

    ...
