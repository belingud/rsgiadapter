import asyncio
import atexit
import inspect
import logging
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from os import PathLike, environ
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable, Optional, Union

from rsgiadapter.constant import (
    DEFAULT_ASGI_VERSION,
    DEFAULT_SPEC_VERSION,
    EventTypeEnum,
)

if TYPE_CHECKING:
    from rsgiadapter.protocol import (
        ASGIScope,
        RSGIHTTPProtocol,
        RSGIHTTPScope,
        RSGIWebsocketProtocol,
        RSGIWebsocketScope,
    )

from rsgiadapter.response import BodyManager, Response

logger = logging.getLogger("rsgiadapter")
if environ.get("RSGI_ADAPTER_DEBUG", "0") == "1":
    logger.setLevel(logging.DEBUG)


class ASGIToRSGI:

    def __init__(
        self,
        asgi_application: Callable[..., Any],
        lifespan: Optional[
            Callable[[Any], AbstractAsyncContextManager] | AbstractAsyncContextManager
        ] = None,
        asgi_version: str = DEFAULT_ASGI_VERSION,
        spec_version: str = DEFAULT_SPEC_VERSION,
    ):
        self.asgi_application = asgi_application
        self.asgi_version = asgi_version
        self.spec_version = spec_version
        self.lifespan = None
        self.register_lifespan(lifespan)

    async def __rsgi__(self, scope, protocol):
        await ASGIToRSGIAdapter(
            self.asgi_application, self.asgi_version, self.spec_version
        )(scope, protocol)

    def register_lifespan(self, lifespan):
        if lifespan is None:
            return
        if inspect.isasyncgenfunction(lifespan):
            lifespan = asynccontextmanager(lifespan)
        elif inspect.isgeneratorfunction(lifespan):
            raise TypeError(
                "generator function lifespans are not supported, "
                "use an @contextlib.asynccontextmanager wrapped callable instead"
            )
        try:
            self.lifespan = lifespan(self.asgi_application)
        except TypeError:
            self.lifespan = lifespan()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.lifespan.__aenter__())
        atexit.register(self.atexit_shutdown)

    def atexit_shutdown(self):
        if self.lifespan is None:
            return
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self.lifespan.__aexit__(None, None, None))
        except Exception as e:
            logger.exception(e)


class ASGIToRSGIAdapter:
    def __init__(
        self,
        asgi_app,
        asgi_version=DEFAULT_ASGI_VERSION,
        spec_version=DEFAULT_SPEC_VERSION,
    ):
        self.asgi_app = asgi_app
        self.asgi_version = asgi_version
        self.spec_version = spec_version
        self.event_status = EventTypeEnum.HTTP_REQUEST

        self.state = {}
        self.response_started = False
        self.response_content_length = None

    async def yield_body(
        self, protocol: Union["RSGIHTTPProtocol", "RSGIWebsocketProtocol"]
    ) -> AsyncGenerator:
        """
        Asynchronously yields messages from the given rsgi `protocol`.

        Args:
            protocol (RSGIHTTPProtocol | RSGIWebsocketProtocol): RSGIHTTPProtocol or RSGIWebsocketProtocol instance.

        Yields:
            Any: The next message from the rsgi protocol.

        """
        async for msg in protocol:
            yield msg

    def make_asgi_scope(
        self, scope: Union["RSGIHTTPScope", "RSGIWebsocketScope"]
    ) -> "ASGIScope":
        """
        Generates an ASGI scope based on RSGI scope, extracting relevant information,
        such as versions, protocol, HTTP version, server details, client details, scheme,
        method, path, query string, headers, and state.

        Args:
            scope (Union["RSGIHTTPScope", "RSGIWebsocketScope"]): The scope object containing the necessary information.

        Returns:
            dict: A dictionary representing the ASGI scope with version details

        Raises:
            ValueError: If the scope is None
        """
        if not scope:
            raise ValueError("Scope cannot be None")

        asgi_version = self.asgi_version
        spec_version = self.spec_version
        proto = scope.proto
        http_version = scope.http_version
        server = scope.server.split(":") if scope.server else []
        client = scope.client.split(":") if scope.client else []
        scheme = scope.scheme
        method = scope.method
        path = scope.path
        raw_path = path.encode("latin-1") if path else b""
        query_string = (
            scope.query_string.encode("latin-1") if scope.query_string else b""
        )
        headers = (
            [
                (k.encode("latin-1"), v.encode("latin-1"))
                for k, v in scope.headers.items()
            ]
            if scope.headers
            else []
        )

        return {
            "asgi": {"version": asgi_version, "spec_version": spec_version},
            "extensions": {"http.response.pathsend": {}},
            "type": proto,
            "http_version": http_version,
            "server": server,
            "client": client,
            "scheme": scheme,
            "method": method,
            "path": path,
            "raw_path": raw_path,
            "query_string": query_string,
            "headers": headers,
            "root_path": "",
            "state": self.state,
        }

    async def __call__(
        self,
        scope: Union["RSGIHTTPScope", "RSGIWebsocketScope"],
        protocol: Union["RSGIHTTPProtocol", "RSGIWebsocketProtocol"],
    ):
        asgi_scope = self.make_asgi_scope(scope)
        send_queue = asyncio.Queue()
        asgi_body = self.yield_body(protocol)

        async def receive():
            try:
                return {
                    "type": self.event_status,
                    "body": await anext(asgi_body),
                    "more_body": True,
                }
            except StopAsyncIteration:
                return {
                    "type": self.event_status,
                    "body": b"",
                    "more_body": False,
                }

        async def send(msg):
            if msg.get("more_body", None) is False:
                self.event_status = EventTypeEnum.HTTP_DISCONNECT
            await send_queue.put(msg)

        try:
            await self.asgi_app(asgi_scope, receive, send)
        except asyncio.CancelledError:
            logger.debug("ASGI app cancelled")
        except Exception:
            logger.info("ASGI app raised an exception", exc_info=True)
        response = await self.get_response(send_queue)

        await self.perform_response(protocol, response)

    async def get_response(self, send_queue: asyncio.Queue):
        response = Response(
            status=None,
            headers=[],
            body=BodyManager(),
            path=None,
            stream=None,
            type=None,
        )
        while not send_queue.empty():
            message = await send_queue.get()
            if message["type"] == EventTypeEnum.HTTP_RESP_START:
                response.status = message["status"]
                response.headers = [
                    (k.decode(), v.decode()) for k, v in message["headers"]
                ]
            elif message["type"] == EventTypeEnum.HTTP_RESP_BODY:
                response.body.append(message["body"])
            elif message["type"] == EventTypeEnum.PATH_SEND:
                response.path = message["path"]
                response.type = EventTypeEnum.PATH_SEND
        return response

    async def perform_response(
        self,
        protocol: Union["RSGIHTTPProtocol", "RSGIWebsocketProtocol"],
        response: Response,
    ) -> None:
        if not response.status:
            return
        if response.path is not None and isinstance(response.path, (str, PathLike)):
            protocol.response_file(
                status=response.status, headers=response.headers, file=response.path
            )
        elif len(response.body) == 0:
            protocol.response_empty(status=response.status, headers=response.headers)
        elif len(response.body) == 1:
            protocol.response_bytes(
                status=response.status,
                headers=response.headers,
                body=response.get_body(),
            )
        elif len(response.body) > 1:
            trx = protocol.response_stream(
                status=response.status,
                headers=response.headers,
            )
            async for chunk in response.body:
                await trx.send_bytes(chunk)
        response.clear_body()
