import asyncio
import inspect
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import CodeType
from unittest.mock import AsyncMock, MagicMock, Mock, NonCallableMock, call

from rsgiadapter import ASGIToRSGI
from rsgiadapter.asgi import ASGIToRSGIAdapter
from rsgiadapter.response import BodyManager, Response


class Stream(Mock):

    send_bytes = AsyncMock()

    send_str = AsyncMock()


class MockAsyncIterator:
    """
    Wraps an iterator in an asynchronous iterator.
    """

    def __init__(self, iterator):
        self.iterator = iterator
        code_mock = NonCallableMock(spec_set=CodeType)
        code_mock.co_flags = inspect.CO_ITERABLE_COROUTINE
        self.__dict__["__code__"] = code_mock

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            pass
        raise StopAsyncIteration

    def __aiter__(self):
        return self


class TestMakeASGIScope(unittest.TestCase):

    def setUp(self):
        self.test_scope = Mock()
        self.test_scope.proto = "http"
        self.test_scope.http_version = "1.1"
        self.test_scope.server = "example.com:80"
        self.test_scope.client = "127.0.0.1:1234"
        self.test_scope.scheme = "https"
        self.test_scope.method = "GET"
        self.test_scope.path = "/test"
        self.test_scope.query_string = "key=value"
        self.test_scope.headers = {"Content-Type": "application/json"}

        self.asgi_app = ASGIToRSGIAdapter(None)

    def test_scope_not_none(self):
        result = self.asgi_app.make_asgi_scope(self.test_scope)
        self.assertIsNotNone(result)

    def test_raise_value_error_if_scope_none(self):
        with self.assertRaises(ValueError):
            self.asgi_app.make_asgi_scope(None)

    def test_correct_attribute_assignment(self):
        result = self.asgi_app.make_asgi_scope(self.test_scope)
        self.assertEqual(result["type"], "http")
        self.assertEqual(result["http_version"], "1.1")
        self.assertEqual(result["server"], ["example.com", "80"])
        self.assertEqual(result["client"], ["127.0.0.1", "1234"])
        self.assertEqual(result["scheme"], "https")
        self.assertEqual(result["method"], "GET")
        self.assertEqual(result["path"], "/test")
        self.assertEqual(result["raw_path"], b"/test")
        self.assertEqual(result["query_string"], b"key=value")
        self.assertEqual(result["headers"], [(b"Content-Type", b"application/json")])


class TestYieldBody(unittest.IsolatedAsyncioTestCase):
    async def test_yield_body(self):
        # Test case: yielding messages from a protocol
        mock_protocol = AsyncMock()

        async def mock_protocol_async_iter():
            yield 1
            yield 2
            yield 3
            # 模拟迭代结束
            raise StopAsyncIteration

        mock_protocol = AsyncMock()

        mock_protocol.__aiter__ = AsyncMock(return_value=mock_protocol_async_iter())

        mock_protocol.__anext__.side_effect = mock_protocol_async_iter()
        mock_protocol = MockAsyncIterator(iter([1, 2, 3]))
        adapter = ASGIToRSGIAdapter(None)
        result = []
        async for msg in adapter.yield_body(mock_protocol):
            result.append(msg)

        self.assertEqual(result, [1, 2, 3])

        # Test case: yielding an empty result
        protocol = MockAsyncIterator(iter([]))

        adapter = ASGIToRSGIAdapter(None)
        result = []
        async for msg in adapter.yield_body(protocol):
            result.append(msg)

        self.assertEqual(result, [])

        # Test case: yielding a single message
        protocol = MockAsyncIterator(iter([4]))

        adapter = ASGIToRSGIAdapter(None)
        result = []
        async for msg in adapter.yield_body(protocol):
            result.append(msg)

        self.assertEqual(result, [4])


class TestPerformResponse(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.protocol = AsyncMock()
        body = BodyManager(chunk_size=5)
        body.append(b"hello")
        body.append(b"world")
        self.response = Response(
            status=200,
            headers=[("Content-Type", "text/plain")],
            body=body,
            path=None,
            stream=None,
            type=None,
        )
        self.mock_response_stream_return = Stream()
        self.protocol.response_stream = Mock(
            return_value=self.mock_response_stream_return
        )
        self.protocol.response_bytes = Mock()
        self.protocol.response_file = Mock()
        self.adapter = ASGIToRSGIAdapter(None, None, None)

    async def test_response_file(self):
        self.response.path = Path("test.txt")
        await self.adapter.perform_response(self.protocol, self.response)
        self.protocol.response_file.assert_called_once_with(
            status=200,
            headers=[("Content-Type", "text/plain")],
            file=Path("test.txt"),
        )

    async def test_response_stream(self):
        await self.adapter.perform_response(self.protocol, self.response)
        self.protocol.response_stream.assert_called_once_with(
            status=200,
            headers=[("Content-Type", "text/plain")],
        )
        self.mock_response_stream_return.send_bytes.assert_has_calls(
            [
                call(b"hello"),
                call(b"world"),
            ]
        )

    async def test_response_bytes(self):
        # single empty chunk: the adapter responds through response_bytes
        self.response.body = BodyManager()
        self.response.body.append(b"")
        await self.adapter.perform_response(self.protocol, self.response)
        self.protocol.response_bytes.assert_called_once_with(
            status=200,
            headers=[("Content-Type", "text/plain")],
            body=b"",
        )


class TestUnsupportedHTTPExtensions(unittest.IsolatedAsyncioTestCase):
    """
    early_hint / push / trailers / zerocopysend / debug are not advertised in
    the http scope extensions (the RSGI server cannot convey them); the
    adapter must consume such messages without breaking the response.
    """

    def make_scope(self):
        scope = Mock()
        scope.proto = "http"
        scope.http_version = "1.1"
        scope.server = "example.com:80"
        scope.client = "127.0.0.1:1234"
        scope.scheme = "https"
        scope.method = "GET"
        scope.path = "/test"
        scope.query_string = ""
        scope.headers = {}
        return scope

    async def test_extension_messages_do_not_break_response(self):
        protocol = Mock()
        protocol.response_bytes = Mock()

        async def app(scope, receive, send):
            await send(
                {
                    "type": "http.response.early_hint",
                    "links": [b"</style.css>; rel=preload; as=style"],
                }
            )
            await send({"type": "http.response.debug", "info": {"msg": "hello"}})
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.push", "path": "/img.png", "headers": []})
            await send(
                {"type": "http.response.body", "body": b"ok", "more_body": False}
            )
            await send(
                {
                    "type": "http.response.trailers",
                    "headers": [(b"x-check", b"1")],
                }
            )

        adapter = ASGIToRSGIAdapter(app)
        await adapter(self.make_scope(), protocol)
        protocol.response_bytes.assert_called_once_with(
            status=200,
            headers=[("content-type", "text/plain")],
            body=b"ok",
        )

    async def test_zerocopysend_message_ignored(self):
        protocol = Mock()
        protocol.response_stream = Mock(return_value=Stream())

        async def app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            )
            await send(
                {"type": "http.response.body", "body": b"chunk1", "more_body": True}
            )
            await send(
                {
                    "type": "http.response.zerocopysend",
                    "file": Mock(),
                    "more_body": True,
                }
            )
            await send(
                {"type": "http.response.body", "body": b"chunk2", "more_body": False}
            )

        adapter = ASGIToRSGIAdapter(app)
        await adapter(self.make_scope(), protocol)
        protocol.response_stream.assert_called_once_with(status=200, headers=[])
        protocol.response_stream.return_value.send_bytes.assert_has_calls(
            [call(b"chunk1"), call(b"chunk2")]
        )


class TestASGIToRSGIWrapper(unittest.TestCase):
    """
    The public wrapper: lifespan registration/exit and __rsgi__ delegation.

    register_lifespan drives its own event loop, so these run as plain
    (synchronous) tests with an explicitly managed loop.
    """

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()
        asyncio.set_event_loop(None)

    async def _noop_app(self, scope, receive, send):
        pass

    def test_no_lifespan(self):
        wrapper = ASGIToRSGI(self._noop_app)
        self.assertIsNone(wrapper.lifespan)
        self.assertEqual(wrapper.asgi_version, "3.0")
        self.assertEqual(wrapper.spec_version, "2.3")
        # atexit_shutdown with no lifespan registered is a no-op
        wrapper.atexit_shutdown()

    def test_debug_env_var_enables_logging(self):
        import importlib
        import logging
        import os

        os.environ["RSGI_ADAPTER_DEBUG"] = "1"
        try:
            asgi_module = importlib.reload(
                importlib.import_module("rsgiadapter.asgi")
            )
            self.assertEqual(asgi_module.logger.level, logging.DEBUG)
        finally:
            os.environ.pop("RSGI_ADAPTER_DEBUG", None)
            importlib.reload(importlib.import_module("rsgiadapter.asgi"))

    def test_asyncgen_function_lifespan(self):
        events = []

        async def lifespan(app):
            events.append("start")
            try:
                yield
            finally:
                events.append("stop")

        wrapper = ASGIToRSGI(self._noop_app, lifespan=lifespan)
        self.assertEqual(events, ["start"])
        wrapper.atexit_shutdown()
        self.assertEqual(events, ["start", "stop"])
        wrapper.lifespan = None  # neutralize the atexit hook

    def test_asynccontextmanager_function_lifespan(self):
        events = []

        @asynccontextmanager
        async def lifespan(app):
            events.append("start")
            try:
                yield
            finally:
                events.append("stop")

        wrapper = ASGIToRSGI(self._noop_app, lifespan=lifespan)
        self.assertEqual(events, ["start"])
        wrapper.atexit_shutdown()
        self.assertEqual(events, ["start", "stop"])
        wrapper.lifespan = None

    def test_zero_arg_lifespan_factory_fallback(self):
        # a factory rejecting the app argument falls back to a zero-arg call
        instances = []

        class FakeCM:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        def build(app=None):
            if app is not None:
                raise TypeError("no app argument accepted")
            cm = FakeCM()
            instances.append(cm)
            return cm

        wrapper = ASGIToRSGI(self._noop_app, lifespan=build)
        self.assertEqual(len(instances), 1)
        wrapper.atexit_shutdown()
        wrapper.lifespan = None

    def test_sync_generator_lifespan_rejected(self):
        def lifespan(app):
            yield

        with self.assertRaises(TypeError):
            ASGIToRSGI(self._noop_app, lifespan=lifespan)

    def test_atexit_shutdown_logs_exceptions(self):
        @asynccontextmanager
        async def bad_lifespan(app):
            yield
            raise RuntimeError("boom")

        wrapper = ASGIToRSGI(self._noop_app, lifespan=bad_lifespan)
        with self.assertLogs("rsgiadapter", level="ERROR") as logs:
            wrapper.atexit_shutdown()
        self.assertIn("boom", "\n".join(logs.output))
        wrapper.lifespan = None


class TestASGIToRSGIEntryPoint(unittest.IsolatedAsyncioTestCase):

    async def test_rsgi_delegates_http_request(self):
        protocol = Mock()
        protocol.response_bytes = Mock()
        scope_types = []

        async def app(scope, receive, send):
            scope_types.append(scope["type"])
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            )
            await send(
                {"type": "http.response.body", "body": b"hi", "more_body": False}
            )

        wrapper = ASGIToRSGI(app)
        scope = Mock()
        scope.proto = "http"
        scope.http_version = "1.1"
        scope.server = "example.com:80"
        scope.client = "127.0.0.1:1234"
        scope.scheme = "https"
        scope.method = "GET"
        scope.path = "/test"
        scope.query_string = ""
        scope.headers = {}
        await wrapper.__rsgi__(scope, protocol)
        self.assertEqual(scope_types, ["http"])
        protocol.response_bytes.assert_called_once_with(
            status=200, headers=[], body=b"hi"
        )


class TestHTTPFlowBranches(unittest.IsolatedAsyncioTestCase):

    def make_scope(self):
        scope = Mock()
        scope.proto = "http"
        scope.http_version = "1.1"
        scope.server = "example.com:80"
        scope.client = "127.0.0.1:1234"
        scope.scheme = "http"
        scope.method = "POST"
        scope.path = "/upload"
        scope.query_string = ""
        scope.headers = {}
        return scope

    def make_body_protocol(self, chunks):
        protocol = MockAsyncIterator(iter(chunks))
        protocol.response_bytes = Mock()
        protocol.response_empty = Mock()
        protocol.response_file = Mock()
        protocol.response_stream = Mock(return_value=Stream())
        return protocol

    async def test_receive_streams_body_then_reports_disconnect(self):
        received = []
        protocol = self.make_body_protocol([b"part1", b"part2"])

        async def app(scope, receive, send):
            for _ in range(3):
                received.append(await receive())
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            )
            await send(
                {"type": "http.response.body", "body": b"done", "more_body": False}
            )
            received.append(await receive())

        await ASGIToRSGIAdapter(app)(self.make_scope(), protocol)
        self.assertEqual(received[0]["type"], "http.request")
        self.assertEqual(received[0]["body"], b"part1")
        self.assertTrue(received[0]["more_body"])
        self.assertEqual(received[1]["body"], b"part2")
        self.assertFalse(received[2]["more_body"])
        self.assertEqual(received[2]["body"], b"")
        # once the response is complete, receives report a disconnect
        self.assertEqual(received[3]["type"], "http.disconnect")
        protocol.response_bytes.assert_called_once_with(
            status=200, headers=[], body=b"done"
        )

    async def test_app_exception_is_logged_without_response(self):
        protocol = Mock()

        async def app(scope, receive, send):
            raise RuntimeError("boom")

        adapter = ASGIToRSGIAdapter(app)
        with self.assertLogs("rsgiadapter", level="INFO") as logs:
            await adapter(self.make_scope(), protocol)
        self.assertIn(
            "ASGI app raised an exception", "\n".join(logs.output)
        )
        # no response was produced: nothing must reach the RSGI protocol
        self.assertEqual(protocol.method_calls, [])

    async def test_app_cancellation_is_logged_at_debug(self):
        protocol = Mock()

        async def app(scope, receive, send):
            raise asyncio.CancelledError()

        adapter = ASGIToRSGIAdapter(app)
        with self.assertLogs("rsgiadapter", level="DEBUG") as logs:
            await adapter(self.make_scope(), protocol)
        self.assertIn("ASGI app cancelled", "\n".join(logs.output))
        self.assertEqual(protocol.method_calls, [])

    async def test_pathsend_message_sets_response_path(self):
        queue = asyncio.Queue()
        await queue.put(
            {
                "type": "http.response.pathsend",
                "path": "/data/file.bin",
            }
        )
        response = await ASGIToRSGIAdapter(None).get_response(queue)
        self.assertEqual(response.path, "/data/file.bin")

    async def test_unsupported_messages_logged_and_trailers_announcement(self):
        queue = asyncio.Queue()
        await queue.put(
            {
                "type": "http.response.start",
                "status": 201,
                "headers": [(b"x-custom", b"yes")],
                "trailers": True,
            }
        )
        await queue.put({"type": "totally.unknown"})

        adapter = ASGIToRSGIAdapter(None)
        with self.assertLogs("rsgiadapter", level="DEBUG") as logs:
            response = await adapter.get_response(queue)
        output = "\n".join(logs.output)
        self.assertIn("trailers was announced", output)
        self.assertIn("Unknown ASGI message type", output)
        self.assertEqual(response.status, 201)
        self.assertEqual(response.headers, [("x-custom", "yes")])


class TestPerformResponseBranches(unittest.IsolatedAsyncioTestCase):

    async def test_no_status_does_nothing(self):
        protocol = Mock()
        response = Response(status=None, headers=[], body=BodyManager())
        await ASGIToRSGIAdapter(None).perform_response(protocol, response)
        self.assertEqual(protocol.method_calls, [])

    async def test_empty_body_uses_response_empty(self):
        protocol = Mock()
        response = Response(status=204, headers=[], body=BodyManager())
        await ASGIToRSGIAdapter(None).perform_response(protocol, response)
        protocol.response_empty.assert_called_once_with(status=204, headers=[])

    async def test_str_path_uses_response_file(self):
        protocol = Mock()
        body = BodyManager()
        body.append(b"ignored")
        response = Response(
            status=200, headers=[], body=body, path="/tmp/static.bin"
        )
        await ASGIToRSGIAdapter(None).perform_response(protocol, response)
        protocol.response_file.assert_called_once_with(
            status=200, headers=[], file="/tmp/static.bin"
        )


if __name__ == "__main__":
    unittest.main()
