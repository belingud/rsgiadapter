import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from rsgiadapter.asgi import ASGIToRSGIAdapter
from rsgiadapter.websocket import (
    ASGIToRSGIWebsocketAdapter,
    DENY_STATUS_DEFAULT,
    DENY_STATUS_ERROR,
    DISCONNECT_ABNORMAL,
    DISCONNECT_NO_CODE,
)

WS_EXTENSIONS = {"websocket.http.response": {}}


class FakeWebsocketTransport:
    """
    Mimics granian's RSGI websocket transport: ``receive`` returns messages
    with ``kind`` (0 close, 1 bytes, 2 string) and ``data``.
    """

    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent = []

    async def receive(self):
        if self.messages:
            return self.messages.pop(0)
        raise RuntimeError("connection closed")

    async def send_bytes(self, data):
        self.sent.append(("bytes", data))

    async def send_str(self, data):
        self.sent.append(("text", data))


def ws_message(kind, data=None):
    if kind == 0:
        return SimpleNamespace(kind=0)
    return SimpleNamespace(kind=kind, data=data)


class FakeProtocol:
    """Mimics granian's RSGIWebsocketProtocol surface."""

    def __init__(self, transport):
        self.transport = transport
        self.accept = AsyncMock(return_value=transport)
        self.close = Mock()

    def make_scope(self):
        scope = Mock()
        scope.proto = "ws"
        scope.http_version = "1.1"
        scope.server = "127.0.0.1:8080"
        scope.client = "127.0.0.1:54321"
        scope.scheme = "http"
        scope.method = "GET"
        scope.path = "/ws"
        scope.query_string = "token=abc"
        scope.headers = {
            "host": "127.0.0.1:8080",
            "sec-websocket-protocol": "graphql, chat",
            "sec-websocket-key": "dGVzdA==",
            "sec-websocket-version": "13",
        }
        return scope


class TestMakeWebsocketScope(unittest.TestCase):

    def setUp(self):
        self.adapter = ASGIToRSGIWebsocketAdapter(None)

    def test_scope_not_none(self):
        scope = FakeProtocol(None).make_scope()
        result = self.adapter.make_asgi_scope(scope)
        self.assertIsNotNone(result)

    def test_raise_value_error_if_scope_none(self):
        with self.assertRaises(ValueError):
            self.adapter.make_asgi_scope(None)

    def test_correct_attribute_assignment(self):
        result = self.adapter.make_asgi_scope(FakeProtocol(None).make_scope())
        self.assertEqual(result["type"], "websocket")
        self.assertEqual(result["scheme"], "ws")
        self.assertEqual(result["http_version"], "1.1")
        self.assertEqual(result["server"], ["127.0.0.1", "8080"])
        self.assertEqual(result["client"], ["127.0.0.1", "54321"])
        self.assertEqual(result["path"], "/ws")
        self.assertEqual(result["raw_path"], b"/ws")
        self.assertEqual(result["query_string"], b"token=abc")
        self.assertEqual(
            result["headers"],
            [
                (b"host", b"127.0.0.1:8080"),
                (b"sec-websocket-protocol", b"graphql, chat"),
                (b"sec-websocket-key", b"dGVzdA=="),
                (b"sec-websocket-version", b"13"),
            ],
        )
        self.assertEqual(result["subprotocols"], ["graphql", "chat"])
        self.assertEqual(result["extensions"], WS_EXTENSIONS)
        # http.response.* extensions never apply to a websocket scope
        self.assertNotIn("http.response.pathsend", result["extensions"])

    def test_tls_scheme(self):
        scope = FakeProtocol(None).make_scope()
        scope.scheme = "https"
        result = self.adapter.make_asgi_scope(scope)
        self.assertEqual(result["scheme"], "wss")

    def test_no_subprotocols(self):
        scope = FakeProtocol(None).make_scope()
        scope.headers = {"host": "127.0.0.1:8080"}
        result = self.adapter.make_asgi_scope(scope)
        self.assertEqual(result["subprotocols"], [])


class TestWebsocketBridge(unittest.IsolatedAsyncioTestCase):

    async def run_app(self, app, transport):
        protocol = FakeProtocol(transport)
        scope = protocol.make_scope()
        await ASGIToRSGIWebsocketAdapter(app)(scope, protocol)
        return protocol

    async def test_accept_echo_and_disconnect(self):
        transport = FakeWebsocketTransport(
            [ws_message(2, "ping"), ws_message(1, b"\x00\x01"), ws_message(0)]
        )
        events = []

        async def app(scope, receive, send):
            events.append(await receive())  # websocket.connect
            await send({"type": "websocket.accept", "subprotocol": "chat"})
            msg = await receive()
            events.append(msg)
            await send({"type": "websocket.send", "text": msg["text"]})
            msg = await receive()
            events.append(msg)
            await send({"type": "websocket.send", "bytes": msg["bytes"]})
            msg = await receive()  # client closed
            events.append(msg)

        protocol = await self.run_app(app, transport)
        self.assertEqual(events[0], {"type": "websocket.connect"})
        self.assertEqual(events[1], {"type": "websocket.receive", "text": "ping"})
        self.assertEqual(events[2], {"type": "websocket.receive", "bytes": b"\x00\x01"})
        self.assertEqual(
            events[3], {"type": "websocket.disconnect", "code": DISCONNECT_NO_CODE}
        )
        protocol.accept.assert_awaited_once()
        # connection closed by the app after the client went away
        self.assertEqual(
            [call.args for call in protocol.close.call_args_list],
            [(None,)],
        )
        self.assertEqual(transport.sent, [("text", "ping"), ("bytes", b"\x00\x01")])

    async def test_denial_response_status_only(self):
        transport = FakeWebsocketTransport()

        async def app(scope, receive, send):
            await receive()
            await send(
                {
                    "type": "websocket.http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send(
                {
                    "type": "websocket.http.response.body",
                    "body": b"denied",
                    "more_body": False,
                }
            )

        protocol = await self.run_app(app, transport)
        protocol.accept.assert_not_awaited()
        # RSGI only conveys the denial status; headers/body are dropped
        self.assertEqual([call.args for call in protocol.close.call_args_list], [(401,)])

    async def test_close_before_accept_denies_with_403(self):
        transport = FakeWebsocketTransport()

        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.close", "code": 1008, "reason": "nope"})

        protocol = await self.run_app(app, transport)
        protocol.accept.assert_not_awaited()
        self.assertEqual(
            [call.args for call in protocol.close.call_args_list],
            [(DENY_STATUS_DEFAULT,)],
        )

    async def test_app_returns_without_decision_denies_with_403(self):
        transport = FakeWebsocketTransport()

        async def app(scope, receive, send):
            await receive()

        protocol = await self.run_app(app, transport)
        protocol.accept.assert_not_awaited()
        self.assertEqual(
            [call.args for call in protocol.close.call_args_list],
            [(DENY_STATUS_DEFAULT,)],
        )

    async def test_app_raises_before_accept_denies_with_500(self):
        transport = FakeWebsocketTransport()

        async def app(scope, receive, send):
            await receive()
            raise RuntimeError("boom")

        protocol = await self.run_app(app, transport)
        protocol.accept.assert_not_awaited()
        self.assertEqual(
            [call.args for call in protocol.close.call_args_list],
            [(DENY_STATUS_ERROR,)],
        )

    async def test_close_after_accept(self):
        transport = FakeWebsocketTransport([ws_message(0)])

        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})
            await receive()  # client closed
            await send({"type": "websocket.close", "code": 1000})

        protocol = await self.run_app(app, transport)
        protocol.accept.assert_awaited_once()
        # the RSGI server drops the close code, the adapter forwards it anyway
        self.assertEqual([call.args for call in protocol.close.call_args_list], [(1000,)])

    async def test_transport_error_reports_abnormal_disconnect(self):
        transport = FakeWebsocketTransport()
        events = []

        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})
            msg = await receive()
            events.append(msg)
            await send({"type": "websocket.close", "code": 1000})

        protocol = await self.run_app(app, transport)
        self.assertEqual(
            events, [{"type": "websocket.disconnect", "code": DISCONNECT_ABNORMAL}]
        )
        protocol.accept.assert_awaited_once()

    async def test_accept_then_app_returns_closes_connection(self):
        transport = FakeWebsocketTransport([ws_message(2, "late")])

        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})

        protocol = await self.run_app(app, transport)
        protocol.accept.assert_awaited_once()
        self.assertEqual([call.args for call in protocol.close.call_args_list], [(None,)])

    async def test_http_adapter_dispatches_websocket_scope(self):
        # the public ASGIToRSGIAdapter must hand ws scopes to the ws bridge
        transport = FakeWebsocketTransport([ws_message(0)])
        events = []

        async def app(scope, receive, send):
            events.append(await receive())
            await send({"type": "websocket.accept"})
            events.append(await receive())

        protocol = FakeProtocol(transport)
        scope = protocol.make_scope()
        await ASGIToRSGIAdapter(app)(scope, protocol)
        self.assertEqual(events[0], {"type": "websocket.connect"})
        self.assertEqual(
            events[1], {"type": "websocket.disconnect", "code": DISCONNECT_NO_CODE}
        )
        protocol.accept.assert_awaited_once()

    async def test_app_raising_after_disconnect_is_not_an_error(self):
        # starlette-like flows unwind with WebSocketDisconnect once the client
        # went away; the adapter must not report it as an app exception
        import logging

        transport = FakeWebsocketTransport([ws_message(2, "hi"), ws_message(0)])

        async def app(scope, receive, send):
            await receive()
            await send({"type": "websocket.accept"})
            while True:
                message = await receive()
                if message["type"] == "websocket.disconnect":
                    raise RuntimeError("starlette.websockets.WebSocketDisconnect")

        with self.assertLogs("rsgiadapter.websocket", level="DEBUG") as logs:
            protocol = await self.run_app(app, transport)
        protocol.accept.assert_awaited_once()
        # connection is finalized with a server-side close, not an error denial
        self.assertEqual(
            [call.args for call in protocol.close.call_args_list], [(None,)]
        )
        # the unwind is only recorded at debug level, not reported as an error
        self.assertEqual(
            [r for r in logs.records if r.levelno >= logging.INFO], []
        )


class TestWebsocketAdapterBranches(unittest.IsolatedAsyncioTestCase):
    """
    Direct unit coverage of the websocket bridge guard branches and logging
    paths that the happy flows do not reach.
    """

    def make_adapter(self):
        return ASGIToRSGIWebsocketAdapter(None)

    async def test_subprotocols_missing_headers(self):
        adapter = self.make_adapter()
        self.assertEqual(adapter._subprotocols(SimpleNamespace(headers=None)), [])
        self.assertEqual(adapter._subprotocols(SimpleNamespace(headers={})), [])

    async def test_receive_after_terminal_close(self):
        adapter = self.make_adapter()
        adapter._connect_sent = True
        adapter._closed = True
        adapter._incoming = asyncio.Queue()
        adapter._terminal_code = None
        self.assertEqual(
            (await adapter.receive())["code"], DISCONNECT_ABNORMAL
        )
        adapter._terminal_code = 1000
        self.assertEqual((await adapter.receive())["code"], 1000)

    async def test_send_after_close_raises(self):
        adapter = self.make_adapter()
        adapter._closed = True
        with self.assertRaises(ConnectionError):
            await adapter.send({"type": "websocket.send", "text": "hi"})

    async def test_unknown_send_message_raises(self):
        adapter = self.make_adapter()
        with self.assertRaisesRegex(RuntimeError, "Unexpected ASGI message"):
            await adapter.send({"type": "websocket.unknown"})

    async def test_accept_after_denial_raises(self):
        adapter = self.make_adapter()
        adapter._denial_status = 401
        with self.assertRaisesRegex(RuntimeError, "after sending a denial"):
            await adapter.send({"type": "websocket.accept"})

    async def test_accept_twice_raises(self):
        adapter = self.make_adapter()
        adapter._accepting = True
        with self.assertRaisesRegex(RuntimeError, "already accepted"):
            await adapter.send({"type": "websocket.accept"})

    async def test_send_message_before_accept_raises(self):
        adapter = self.make_adapter()
        with self.assertRaisesRegex(RuntimeError, "not accepted"):
            await adapter.send({"type": "websocket.send", "text": "hi"})

    async def test_send_message_without_payload_raises(self):
        adapter = self.make_adapter()
        adapter._accepted = True
        adapter._transport = FakeWebsocketTransport()
        with self.assertRaisesRegex(RuntimeError, "bytes.*text"):
            await adapter.send({"type": "websocket.send"})

    async def test_denial_body_without_start_raises(self):
        adapter = self.make_adapter()
        with self.assertRaisesRegex(RuntimeError, "before"):
            await adapter.send(
                {
                    "type": "websocket.http.response.body",
                    "body": b"x",
                    "more_body": False,
                }
            )

    async def test_denial_start_twice_raises(self):
        adapter = self.make_adapter()
        adapter._denial_status = 401
        with self.assertRaisesRegex(RuntimeError, "already started"):
            await adapter.send(
                {
                    "type": "websocket.http.response.start",
                    "status": 403,
                    "headers": [],
                }
            )

    async def test_denial_start_after_accept_raises(self):
        adapter = self.make_adapter()
        adapter._accepted = True
        with self.assertRaisesRegex(RuntimeError, "after accepting"):
            await adapter.send(
                {
                    "type": "websocket.http.response.start",
                    "status": 403,
                }
            )

    async def test_close_after_denial_uses_denial_status(self):
        protocol = FakeProtocol(None)
        adapter = self.make_adapter()
        adapter.protocol = protocol
        adapter._denial_status = 451
        await adapter.send({"type": "websocket.close", "code": 1000})
        self.assertEqual([c.args for c in protocol.close.call_args_list], [(451,)])

    async def test_close_with_reason_before_accept_denies_403(self):
        protocol = FakeProtocol(None)
        adapter = self.make_adapter()
        adapter.protocol = protocol
        await adapter.send(
            {"type": "websocket.close", "code": 1000, "reason": "bye"}
        )
        protocol.accept.assert_not_awaited()
        self.assertEqual(
            [c.args for c in protocol.close.call_args_list], [(403,)]
        )

    async def test_pump_unknown_kind_warns_and_reports_abnormal_close(self):
        transport = FakeWebsocketTransport(
            [SimpleNamespace(kind=99, data=b"odd")]
        )
        adapter = self.make_adapter()
        adapter._incoming = asyncio.Queue()
        with self.assertLogs("rsgiadapter.websocket", level="WARNING") as logs:
            await adapter._pump(transport)
        self.assertIn(
            "Unknown RSGI websocket message kind", "\n".join(logs.output)
        )
        message = adapter._incoming.get_nowait()
        self.assertEqual(message["type"], "websocket.disconnect")
        self.assertEqual(message["code"], DISCONNECT_ABNORMAL)

    async def test_app_cancellation_denies_connection(self):
        transport = FakeWebsocketTransport()

        async def app(scope, receive, send):
            await receive()
            raise asyncio.CancelledError()

        protocol = FakeProtocol(transport)
        scope = protocol.make_scope()
        with self.assertLogs("rsgiadapter.websocket", level="DEBUG") as logs:
            await ASGIToRSGIWebsocketAdapter(app)(scope, protocol)
        self.assertIn("ASGI app cancelled", "\n".join(logs.output))
        protocol.accept.assert_not_awaited()
        self.assertEqual(
            [c.args for c in protocol.close.call_args_list], [(403,)]
        )

    async def test_denial_started_but_not_completed(self):
        transport = FakeWebsocketTransport()

        async def app(scope, receive, send):
            await receive()
            await send(
                {
                    "type": "websocket.http.response.start",
                    "status": 451,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            # returns without sending the denial body

        protocol = FakeProtocol(transport)
        await ASGIToRSGIWebsocketAdapter(app)(protocol.make_scope(), protocol)
        protocol.accept.assert_not_awaited()
        self.assertEqual([c.args for c in protocol.close.call_args_list], [(451,)])

    async def test_receive_pump_finished_fallback_reports_disconnect(self):
        adapter = self.make_adapter()
        adapter._connect_sent = True
        adapter._incoming = asyncio.Queue()

        async def noop():
            return None

        task = asyncio.get_running_loop().create_task(noop())
        await task
        adapter._pump_task = task
        message = await adapter.receive()
        self.assertEqual(
            message, {"type": "websocket.disconnect", "code": DISCONNECT_NO_CODE}
        )
        self.assertTrue(adapter._disconnect_delivered)

    async def test_accept_with_custom_headers_is_dropped_with_note(self):
        protocol = FakeProtocol(FakeWebsocketTransport())
        adapter = self.make_adapter()
        adapter.protocol = protocol
        with self.assertLogs("rsgiadapter.websocket", level="DEBUG") as logs:
            await adapter.send(
                {
                    "type": "websocket.accept",
                    "headers": [(b"x-custom", b"yes")],
                }
            )
        self.assertIn(
            "cannot add custom accept headers", "\n".join(logs.output)
        )
        protocol.accept.assert_awaited_once()

    async def test_terminate_twice_is_a_noop(self):
        protocol = FakeProtocol(None)
        adapter = self.make_adapter()
        adapter.protocol = protocol
        adapter._terminate(1000)
        adapter._terminate(1000)
        self.assertEqual([c.args for c in protocol.close.call_args_list], [(1000,)])

    async def test_terminate_warns_when_close_fails(self):
        protocol = Mock()
        protocol.close = Mock(side_effect=RuntimeError("close failed"))
        adapter = self.make_adapter()
        adapter.protocol = protocol
        with self.assertLogs("rsgiadapter.websocket", level="WARNING") as logs:
            adapter._terminate(1000)
        self.assertIn("Failed to close", "\n".join(logs.output))

    async def test_start_pump_keeps_running_task(self):
        adapter = self.make_adapter()

        async def pending():
            await asyncio.Event().wait()

        task = asyncio.get_running_loop().create_task(pending())
        try:
            adapter._pump_task = task
            self.assertIs(adapter._start_pump(None), task)
        finally:
            task.cancel()

    async def test_pump_cancellation_propagates(self):
        class BlockingTransport:
            async def receive(self):
                await asyncio.Event().wait()

        adapter = self.make_adapter()
        adapter._incoming = asyncio.Queue()
        task = asyncio.get_running_loop().create_task(
            adapter._pump(BlockingTransport())
        )
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
