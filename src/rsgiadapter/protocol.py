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

    def response_bytes(self, *args, **kwargs):
        pass

    def response_empty(self, *args, **kwargs):
        pass

    def response_file(self, *args, **kwargs):
        pass

    def response_str(self, *args, **kwargs):
        pass

    def response_stream(self, *args, **kwargs):
        pass

    def __aiter__(self, *args, **kwargs):
        return self

    async def __anext__(self, *args, **kwargs):
        if self.data:
            return self.data.pop(0)
        raise StopAsyncIteration

    def __call__(self, *args, **kwargs):
        pass

    def __init__(self, *args, **kwargs):
        self.data = list(args)

    @staticmethod
    def __new__(cls, *args, **kwargs):
        pass


class RSGIWebsocketProtocol(object):
    def accept(self, *args, **kwargs):
        pass

    def close(self, *args, **kwargs):
        pass

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def __new__(cls, *args, **kwargs):
        pass


class RSGIWebsocketScope(RSGIHTTPScope):
    pass
