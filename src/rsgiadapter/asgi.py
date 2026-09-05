"""
Bridges ASGI applications to RSGI servers.

An RSGI server (e.g. granian) calls the application once per connection with
an RSGI scope and protocol object. This module adapts HTTP connections to the
ASGI HTTP protocol (``http.request``/``http.response.*``) and dispatches
WebSocket upgrade connections to :mod:`rsgiadapter.websocket`.
"""

import asyncio
import atexit
import inspect
import logging
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from os import PathLike, environ
from typing import TYPE_CHECKING, Any, AsyncGenerator, AsyncIterator, Callable, Optional, Union, cast
from rsgiadapter.constant import (
    DEFAULT_ASGI_VERSION,
    DEFAULT_SPEC_VERSION,
    EventTypeEnum,
)
from rsgiadapter.websocket import ASGIToRSGIWebsocketAdapter

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
# RSGI_ADAPTER_DEBUG=1 enables the adapter's debug logging (extension
# messages that are consumed silently, dropped close codes, ...)
if environ.get("RSGI_ADAPTER_DEBUG", "0") == "1":
    logger.setLevel(logging.DEBUG)


class ASGIToRSGI:
    """
    Wraps an ASGI application so that an RSGI server can run it.

    Exposes the RSGI application interface (``__rsgi__``) expected by RSGI
    servers. A lifespan may be passed in and is entered on startup and exited
    at process exit.
    """

    def __init__(
        self,
        asgi_application: Callable[..., Any],
        lifespan: Optional[
            Callable[[Any], AbstractAsyncContextManager]
            | Callable[[Any], AsyncGenerator[Any, Any]]
            | AbstractAsyncContextManager
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
        """
        RSGI entry point: called once per connection by the RSGI server.

        A fresh per-connection adapter is created for every request so that
        per-connection state (ASGI ``state``, response state) never leaks
        between connections.
        """
        await ASGIToRSGIAdapter(
            self.asgi_application, self.asgi_version, self.spec_version
        )(scope, protocol)

    def register_lifespan(self, lifespan):
        """
        Registers and enters an ASGI lifespan context manager.

        Accepts either an ``@asynccontextmanager``-decorated function (or a
        raw async generator function, which is decorated on the fly) or an
        already-created async context manager. Plain generator functions are
        rejected since they cannot provide asynchronous startup/shutdown.
        """
        if lifespan is None:
            return
        if inspect.isasyncgenfunction(lifespan):
            lifespan = asynccontextmanager(lifespan)
        elif inspect.isgeneratorfunction(lifespan):
            raise TypeError(
                "generator function lifespans are not supported, "
                "use an @contextlib.asynccontextmanager wrapped callable instead"
            )
        # build the context manager; frameworks usually define lifespans that
        # take the application instance as an argument
        try:
            self.lifespan = lifespan(self.asgi_application)
        except TypeError:
            self.lifespan = lifespan()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.lifespan.__aenter__())
        atexit.register(self.atexit_shutdown)

    def atexit_shutdown(self):
        """
        Exits the lifespan context manager at interpreter shutdown.

        RSGI (unlike ASGI) has no in-band lifespan protocol for the server to
        drive, so shutdown runs on the registered atexit hook.
        """
        if self.lifespan is None:
            return
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self.lifespan.__aexit__(None, None, None))
        except Exception as e:
            logger.exception(e)


class ASGIToRSGIAdapter:
    """
    Adapts one RSGI connection (HTTP request) to one ASGI application call.

    The adapter is created per connection: it translates the RSGI scope into
    an ASGI HTTP scope, streams the RSGI request body into ASGI
    ``http.request`` receive events, collects ASGI ``http.response.*`` send
    events and finally pushes the response through the RSGI protocol object.
    WebSocket upgrade connections are forwarded to the websocket bridge.
    """

    def __init__(
        self,
        asgi_app,
        asgi_version=DEFAULT_ASGI_VERSION,
        spec_version=DEFAULT_SPEC_VERSION,
    ):
        self.asgi_app = asgi_app
        self.asgi_version = asgi_version
        self.spec_version = spec_version
        # receive events are emitted with this type; once the application has
        # completed its response, further receives report an http.disconnect
        self.event_status = EventTypeEnum.HTTP_REQUEST

        # ASGI scope state; lives as long as this connection does
        self.state = {}
        self.response_started = False
        self.response_content_length = None

    async def yield_body(
        self, protocol: "AsyncIterator[Any]"
    ) -> AsyncGenerator[Any, None]:
        """
        Asynchronously yields request body chunks from the RSGI HTTP protocol.

        Only HTTP connections carry an iterable request body; websocket
        connections are handled by the websocket bridge instead.

        Args:
            protocol (RSGIHTTPProtocol): the RSGI HTTP protocol instance.

        Yields:
            Any: The next body chunk from the rsgi protocol.

        """
        async for msg in protocol:
            yield msg

    def make_asgi_scope(
        self, scope: Optional[Union["RSGIHTTPScope", "RSGIWebsocketScope"]]
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
        """
        Runs the ASGI application for a single RSGI connection.

        WebSocket upgrade requests (RSGI scope ``proto == "ws"``) are handed
        to the websocket bridge; every other connection follows the HTTP flow.
        """
        # RSGI servers call the application with a websocket scope/protocol
        # for upgrade requests: bridge those to the ASGI websocket protocol.
        # The RSGI scope classes are structural templates only (never
        # importable at runtime), so the branch uses a proto marker + cast.
        if getattr(scope, "proto", None) == "ws":
            await ASGIToRSGIWebsocketAdapter(
                self.asgi_app, self.asgi_version, self.spec_version
            )(
                cast("RSGIWebsocketScope", scope),
                cast("RSGIWebsocketProtocol", protocol),
            )
            return

        asgi_scope = self.make_asgi_scope(scope)
        # outgoing ASGI messages are buffered until the application returns,
        # then drained by get_response() and flushed by perform_response()
        send_queue = asyncio.Queue()
        asgi_body = self.yield_body(cast("RSGIHTTPProtocol", protocol))

        async def receive():
            """
            ASGI receive: yields one request body chunk per call.

            The RSGI protocol is iterated lazily; once the request body is
            exhausted, further receives report an empty final chunk, or an
            ``http.disconnect`` once the response has been completed.
            """
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
            """
            ASGI send: buffers one outgoing message.

            After the application signals the last response body chunk
            (``more_body`` is False), subsequent receive() calls report an
            ``http.disconnect`` so long-polling applications can clean up.
            """
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

        await self.perform_response(cast("RSGIHTTPProtocol", protocol), response)

    async def get_response(self, send_queue: asyncio.Queue) -> Response:
        """
        Drains the buffered ASGI send messages into a :class:`Response`.

        Response state is accumulated from ``http.response.start``,
        ``http.response.body`` and ``http.response.pathsend`` messages.
        Extension messages that the RSGI server cannot convey
        (``early_hint``/``push``/``trailers``/``zerocopysend``/``debug``) are
        consumed here - logged and dropped - so misbehaving applications do
        not break the response.
        """
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
            message_type = message.get("type")
            if message_type == EventTypeEnum.HTTP_RESP_START:
                response.status = message["status"]
                response.headers = [
                    (k.decode(), v.decode()) for k, v in message["headers"]
                ]
                if message.get("trailers"):
                    logger.debug(
                        "http.response.trailers was announced in response start "
                        "but the RSGI server cannot send trailers"
                    )
            elif message_type == EventTypeEnum.HTTP_RESP_BODY:
                response.body.append(message["body"])
            elif message_type == EventTypeEnum.PATH_SEND:
                response.path = message["path"]
                response.type = EventTypeEnum.PATH_SEND
            elif message_type == EventTypeEnum.HTTP_DEBUG:
                # debug data is destined to the server, never to the wire
                logger.debug("http.response.debug: %s", message.get("info"))
            elif message_type == EventTypeEnum.EARLY_HINT:
                # 103 informational responses cannot be emitted through the
                # RSGI interface; the spec allows servers to ignore them
                logger.debug(
                    "http.response.early_hint ignored, the RSGI server cannot "
                    "send informational responses: %s",
                    message.get("links"),
                )
            elif message_type in (
                EventTypeEnum.HTTP_PUSH,
                EventTypeEnum.TRAILERS,
                EventTypeEnum.ZERO_COPY_SEND,
            ):
                # not advertised in scope extensions and not conveyable on the
                # RSGI wire; consume the message so applications do not break
                logger.warning(
                    "%s is not supported by the RSGI server, message ignored",
                    message_type,
                )
            else:
                logger.warning("Unknown ASGI message type %r", message_type)
        return response

    async def perform_response(
        self,
        protocol: "RSGIHTTPProtocol",
        response: Response,
    ) -> None:
        """
        Sends the accumulated :class:`Response` through the RSGI protocol.

        Selects the RSGI response method based on the response shape:
        a file path uses ``response_file``, an empty body ``response_empty``,
        a single chunk ``response_bytes`` and multiple chunks a streaming
        ``response_stream`` transport.
        """
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
