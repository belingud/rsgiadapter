"""
WebSocket bridge: adapts an RSGI websocket connection to an ASGI application.

RSGI servers hand websocket upgrade requests to the application with a scope
whose ``proto`` is ``"ws"`` and an ``RSGIWebsocketProtocol``. This module
translates the RSGI websocket surface (``accept``/``close`` plus a transport
with ``receive``/``send_bytes``/``send_str``) into the ASGI websocket events
(``websocket.connect``/``receive``/``disconnect`` and
``websocket.accept``/``send``/``close``) plus the ``websocket.http.response``
denial extension.
"""

import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from rsgiadapter.constant import (
    DEFAULT_ASGI_VERSION,
    DEFAULT_SPEC_VERSION,
    EventTypeEnum,
)

if TYPE_CHECKING:
    from rsgiadapter.protocol import (
        RSGIWebsocketProtocol,
        RSGIWebsocketScope,
        RSGIWebsocketTransport,
    )

logger = logging.getLogger("rsgiadapter.websocket")

# Core ASGI websocket spec: a close sent (or an application return without a
# decision) before the socket is accepted must deny the upgrade with HTTP 403.
DENY_STATUS_DEFAULT = 403
# ASGI application raised before accepting the connection.
DENY_STATUS_ERROR = 500
# WebSocket close codes used when the RSGI transport does not provide one.
DISCONNECT_NO_CODE = 1005  # RFC 6455: no status code was received
DISCONNECT_ABNORMAL = 1006  # connection closed without a close handshake
CLOSE_NORMAL = 1000

# RSGI servers report the transport scheme as http/https even for websocket
# scopes; ASGI websocket scopes expect ws/wss instead.
_WS_SCHEME_MAP = {"http": "ws", "https": "wss"}


class ASGIToRSGIWebsocketAdapter:
    """
    Bridges a single RSGI websocket connection to an ASGI application.

    RSGI servers hand websocket upgrades to the application with a scope whose
    ``proto`` is ``"ws"`` and a ``RSGIWebsocketProtocol`` object. ASGI expects
    to drive the connection with ``websocket.connect`` / ``websocket.receive``
    / ``websocket.disconnect`` receive events and ``websocket.accept`` /
    ``websocket.send`` / ``websocket.close`` send events, plus the
    ``websocket.http.response`` denial extension.

    Capabilities of the bridge are bounded by the RSGI protocol surface:

    - ``accept`` cannot negotiate a subprotocol nor add response headers
    - a denial (``websocket.http.response.start/body``) is transmitted as an
      HTTP response carrying the status code only: custom denial headers and
      body cannot cross the RSGI boundary yet
    - after acceptance, ``close`` codes and reasons are not conveyed to the
      client by the RSGI server (see https://github.com/emmett-framework/granian/issues/645)
    """

    def __init__(
        self,
        asgi_application: Callable[..., Any],
        asgi_version: str = DEFAULT_ASGI_VERSION,
        spec_version: str = DEFAULT_SPEC_VERSION,
    ):
        self.asgi_app = asgi_application
        self.asgi_version = asgi_version
        self.spec_version = spec_version
        # ASGI scope state; lives as long as this connection does
        self.state = {}
        # RSGI protocol handed over by the server in __call__
        self.protocol: Optional["RSGIWebsocketProtocol"] = None
        # accepted RSGI transport; set by _accept
        self._transport: Optional["RSGIWebsocketTransport"] = None

        # conversation state machine:
        # - _connect_sent: the initial websocket.connect event was consumed
        # - _accepting/_accepted: handshake in progress / completed
        # - _closed: a terminal decision (accept-and-close, denial, ...) ran
        # - _disconnect_delivered: the app was told the client went away
        # - _denial_status: HTTP status chosen by the denial response
        # - _terminal_code: close code surfaced to receive() after closure
        self._connect_sent = False
        self._accepted = False
        self._accepting = False
        self._closed = False
        self._disconnect_delivered = False
        self._denial_status: Optional[int] = None
        self._terminal_code: Optional[int] = None
        # ASGI receive events produced by the transport pump task; __call__
        # installs a fresh, bounded queue for every connection
        self._incoming: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._pump_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ scope

    def make_asgi_scope(
        self, scope: Optional["RSGIWebsocketScope"]
    ) -> Dict[str, Any]:
        """
        Generates an ASGI websocket scope from the RSGI websocket scope.

        Args:
            scope: The RSGI websocket scope object.

        Returns:
            dict: An ASGI websocket connection scope.
        """
        if not scope:
            raise ValueError("Scope cannot be None")

        scheme = _WS_SCHEME_MAP.get(scope.scheme, scope.scheme)
        server = scope.server.rsplit(":", 1) if scope.server else []
        client = scope.client.rsplit(":", 1) if scope.client else []
        path = scope.path or ""
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
            "type": "websocket",
            "asgi": {"version": self.asgi_version, "spec_version": self.spec_version},
            # websocket scopes only advertise the denial response extension;
            # http.response.* extensions never apply to a websocket scope
            "extensions": {
                "websocket.http.response": {},
            },
            "http_version": scope.http_version,
            "scheme": scheme,
            "path": path,
            "raw_path": path.encode("latin-1"),
            "query_string": query_string,
            "root_path": "",
            "headers": headers,
            "client": client,
            "server": server,
            "subprotocols": self._subprotocols(scope),
            "state": self.state,
        }

    @staticmethod
    def _subprotocols(scope: "RSGIWebsocketScope") -> List[str]:
        """
        Extracts the subprotocols advertised by the client.

        The ``sec-websocket-protocol`` request header may appear multiple
        times and may carry a comma separated list; values are split and
        trimmed, preserving the order.
        """
        subprotocols = []
        headers = scope.headers
        if not headers:
            return subprotocols
        items = headers.items() if hasattr(headers, "items") else []
        for name, value in items:
            if name.lower() == "sec-websocket-protocol":
                subprotocols.extend(
                    part.strip() for part in value.split(",") if part.strip()
                )
        return subprotocols

    # ---------------------------------------------------------------- driver

    async def __call__(
        self,
        scope: "RSGIWebsocketScope",
        protocol: "RSGIWebsocketProtocol",
    ):
        """
        Runs the ASGI application for one RSGI websocket connection.

        The application drives the whole conversation; when it returns (or
        raises), the connection is finalized: an accepted-but-open socket is
        closed by the RSGI server, an undecided connection is denied with
        HTTP 403 (or 500 when the application raised).
        """
        self.protocol = protocol
        asgi_scope = self.make_asgi_scope(scope)
        # incoming queue feeds receive(); the pump task keeps it filled from
        # the RSGI transport. maxsize bounds memory when the app is slow.
        self._incoming = asyncio.Queue(maxsize=32)

        raised = False
        try:
            await self.asgi_app(asgi_scope, self.receive, self.send)
        except asyncio.CancelledError:
            logger.debug("ASGI app cancelled")
        except Exception:
            if self._disconnect_delivered:
                # the client already went away and the app was told about it:
                # frameworks commonly unwind with an exception here (e.g.
                # starlette's WebSocketDisconnect), nothing to report
                logger.debug(
                    "ASGI app raised an exception after the client disconnect",
                    exc_info=True,
                )
            else:
                logger.info("ASGI app raised an exception", exc_info=True)
            raised = True
        finally:
            if not self._closed:
                if self._denial_status is not None:
                    # a denial was started but never completed by the app
                    self._terminate(self._denial_status)
                elif self._accepted:
                    # the RSGI server closes the socket when the callback
                    # ends; no close code can be conveyed at this point
                    self._terminate(None)
                else:
                    status = DENY_STATUS_ERROR if raised else DENY_STATUS_DEFAULT
                    if not raised:
                        logger.warning(
                            "ASGI websocket application returned without "
                            "accepting or denying the connection"
                        )
                    self._terminate(status)
            self._stop_pump()

    # -------------------------------------------------------------- asgi api

    async def receive(self) -> Dict[str, Any]:
        """
        ASGI receive: yields the initial ``websocket.connect`` event, then
        events produced by the transport pump task.

        Disconnect reporting follows the client side of the connection:
        once the client has gone away (or the connection was terminated), the
        app receives ``websocket.disconnect`` events; every message delivered
        marks ``_disconnect_delivered`` so that a subsequent application
        unwind is not reported as an error.
        """
        if not self._connect_sent:
            self._connect_sent = True
            return {"type": EventTypeEnum.WEBSOCKET_CONNECT}
        if self._closed:
            # terminal decision already taken on the wire (close/denial):
            # report the closure to any straggling receive() call
            return {
                "type": EventTypeEnum.WEBSOCKET_DISCONNECT,
                "code": self._terminal_code
                if self._terminal_code is not None
                else DISCONNECT_ABNORMAL,
            }
        queue = self._incoming
        if not queue.empty():
            message = await queue.get()
            if message["type"] == EventTypeEnum.WEBSOCKET_DISCONNECT:
                self._disconnect_delivered = True
            return message
        if self._pump_finished():
            # the client connection ended and queued events were drained
            self._disconnect_delivered = True
            return {
                "type": EventTypeEnum.WEBSOCKET_DISCONNECT,
                "code": DISCONNECT_NO_CODE,
            }
        message = await queue.get()
        if message["type"] == EventTypeEnum.WEBSOCKET_DISCONNECT:
            self._disconnect_delivered = True
        return message

    async def send(self, message: Dict[str, Any]):
        """
        ASGI send: dispatches ``websocket.accept`` / ``websocket.send`` /
        ``websocket.close`` and the ``websocket.http.response`` denial events
        to the RSGI protocol.
        """
        if self._closed:
            raise ConnectionError("Websocket connection already closed")

        message_type = message["type"]
        if message_type == EventTypeEnum.WEBSOCKET_ACCEPT:
            await self._accept(message)
        elif message_type == EventTypeEnum.WEBSOCKET_SEND:
            await self._send_message(message)
        elif message_type == EventTypeEnum.WEBSOCKET_CLOSE:
            self._send_close(message)
        elif message_type == EventTypeEnum.WS_HTTP_RESP_START:
            self._denial_start(message)
        elif message_type == EventTypeEnum.WS_HTTP_RESP_BODY:
            self._denial_body(message)
        else:
            raise RuntimeError(f"Unexpected ASGI message '{message_type}'")

    # ------------------------------------------------------------- send side

    async def _accept(self, message: Dict[str, Any]):
        """
        Handles ``websocket.accept``: completes the RSGI handshake.

        The RSGI accept cannot negotiate a subprotocol nor attach custom
        response headers, so both are dropped with a debug note. The returned
        transport feeds the receive pump; ``_accepting`` guards against
        concurrent accepts (the RSGI server would panic on a second one).
        """
        if self._accepted or self._accepting:
            raise RuntimeError("Websocket already accepted")
        if self._denial_status is not None:
            raise RuntimeError(
                "Cannot accept the websocket after sending a denial response"
            )
        subprotocol = message.get("subprotocol")
        if subprotocol:
            logger.debug(
                "RSGI websocket cannot negotiate subprotocols, ignoring %r",
                subprotocol,
            )
        headers = message.get("headers")
        if headers:
            logger.debug(
                "RSGI websocket cannot add custom accept headers, ignoring %r",
                headers,
            )
        # granian's RSGI accept takes no arguments and returns the transport;
        # the protocol is always installed by __call__ before the app runs
        protocol = self.protocol
        assert protocol is not None, "RSGI protocol not initialized"
        self._accepting = True
        try:
            transport = await protocol.accept()
        finally:
            self._accepting = False
        self._transport = transport
        self._accepted = True
        self._start_pump(self._transport)

    async def _send_message(self, message: Dict[str, Any]):
        """
        Handles ``websocket.send``: forwards one data message to the client.

        Exactly one of ``bytes`` or ``text`` must be present, mirroring the
        ASGI websocket send contract.
        """
        if not self._accepted:
            raise RuntimeError("Websocket not accepted yet")
        transport = self._transport
        assert transport is not None, "Websocket transport not initialized"
        if message.get("bytes") is not None:
            await transport.send_bytes(message["bytes"])
        elif message.get("text") is not None:
            await transport.send_str(message["text"])
        else:
            raise RuntimeError("websocket.send message requires a 'bytes' or 'text' key")

    def _send_close(self, message: Dict[str, Any]):
        """
        Handles ``websocket.close``: terminates the connection.

        Per the core ASGI spec a close sent before acceptance denies the
        handshake with HTTP 403. After acceptance the RSGI server drops the
        close code/reason, so only the code (or None) is forwarded; a close
        racing an in-flight denial response simply completes that denial.
        """
        code = message.get("code")
        reason = message.get("reason")
        if self._denial_status is not None:
            if code or reason:
                logger.debug(
                    "Close code/reason after a denial response are dropped: %r %r",
                    code,
                    reason,
                )
            self._terminate(self._denial_status)
            return
        if not self._accepted:
            # core ASGI: close before accept denies the handshake with HTTP 403
            if code not in (None, CLOSE_NORMAL) or reason:
                logger.debug(
                    "Close code/reason before acceptance are dropped, denying "
                    "with 403: %r %r",
                    code,
                    reason,
                )
            self._terminate(DENY_STATUS_DEFAULT)
            return
        if code or reason:
            logger.debug(
                "RSGI websocket cannot convey close code/reason, ignoring %r %r",
                code,
                reason,
            )
        self._terminate(code if code is not None else None)

    def _denial_start(self, message: Dict[str, Any]):
        """
        Handles ``websocket.http.response.start`` (denial extension).

        Records the denial status; the response is transmitted when the
        denial body completes (or the application ends). Custom headers
        cannot cross the RSGI boundary and are dropped.
        """
        if self._accepted:
            raise RuntimeError(
                "Cannot send a denial response after accepting the websocket"
            )
        if self._denial_status is not None:
            raise RuntimeError("Denial response already started")
        self._denial_status = message.get("status")
        if message.get("headers"):
            logger.debug(
                "RSGI websocket denial response carries the status code only, "
                "custom headers are dropped"
            )

    def _denial_body(self, message: Dict[str, Any]):
        """
        Handles ``websocket.http.response.body`` (denial extension).

        The body content itself cannot cross the RSGI boundary; the last
        chunk (``more_body`` False) transmits the denial status.
        """
        if self._denial_status is None:
            raise RuntimeError(
                "websocket.http.response.body sent before "
                "websocket.http.response.start"
            )
        if message.get("body"):
            logger.debug(
                "RSGI websocket denial response carries the status code only, "
                "body content is dropped"
            )
        if not message.get("more_body", False):
            self._terminate(self._denial_status)

    def _terminate(self, status: Optional[int]):
        """
        Ends the connection through the RSGI protocol.

        A non-None ``status`` sent before acceptance is emitted as the HTTP
        status of the denial response; after acceptance the RSGI server uses
        it as the websocket close code (currently dropped upstream).
        """
        if self._closed:
            return
        self._closed = True
        self._terminal_code = (
            status if status is not None else CLOSE_NORMAL
        )
        protocol = self.protocol
        assert protocol is not None, "RSGI protocol not initialized"
        try:
            protocol.close(status)
        except Exception:
            logger.warning(
                "Failed to close the RSGI websocket protocol", exc_info=True
            )
        self._stop_pump()

    # --------------------------------------------------------- receive side

    def _pump_finished(self) -> bool:
        """True when the receive pump has exited (client side gone)."""
        return self._pump_task is not None and self._pump_task.done()

    def _start_pump(self, transport):
        """Starts the pump task reading from the accepted transport."""
        if self._pump_task is not None and not self._pump_task.done():
            return self._pump_task
        loop = asyncio.get_running_loop()
        self._pump_task = loop.create_task(self._pump(transport))
        return self._pump_task

    async def _pump(self, transport) -> None:
        """
        Reads messages from the RSGI websocket transport and feeds the ASGI
        ``receive`` queue. ``kind`` 0 means the client closed the connection,
        1 is a bytes message and 2 is a string message.
        """
        queue = self._incoming
        try:
            while True:
                message = await transport.receive()
                kind = getattr(message, "kind", None)
                data = getattr(message, "data", None)
                if kind == 0:
                    # the client sent a close frame (its code is not conveyed
                    # by the RSGI transport): report a code-less disconnect
                    await queue.put(
                        {
                            "type": EventTypeEnum.WEBSOCKET_DISCONNECT,
                            "code": DISCONNECT_NO_CODE,
                        }
                    )
                    return
                if kind == 1:
                    await queue.put(
                        {
                            "type": EventTypeEnum.WEBSOCKET_RECEIVE,
                            "bytes": data,
                        }
                    )
                elif kind == 2:
                    await queue.put(
                        {
                            "type": EventTypeEnum.WEBSOCKET_RECEIVE,
                            "text": data,
                        }
                    )
                else:
                    logger.warning("Unknown RSGI websocket message kind %r", kind)
        except asyncio.CancelledError:
            raise
        except Exception:
            # connection lost or transport error: report an abnormal closure.
            # the queue is bounded, so a blocked put keeps memory in check
            if not self._closed:
                with suppress(Exception):
                    await queue.put(
                        {
                            "type": EventTypeEnum.WEBSOCKET_DISCONNECT,
                            "code": DISCONNECT_ABNORMAL,
                        }
                    )

    def _stop_pump(self):
        """
        Cancels the receive pump task without awaiting it.

        The underlying RSGI receive may not honour task cancellation until
        the connection closes, so waiting for it could hang the caller.
        """
        task = self._pump_task
        if task is not None and not task.done():
            task.cancel()
