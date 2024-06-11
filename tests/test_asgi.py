import inspect
import unittest
from pathlib import Path
from types import CodeType
from unittest.mock import AsyncMock, MagicMock, Mock, NonCallableMock, call

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
        self.response.body = BodyManager()
        await self.adapter.perform_response(self.protocol, self.response)
        self.protocol.response_bytes.assert_called_once_with(
            status=200,
            headers=[("Content-Type", "text/plain")],
            body=b"",
        )


if __name__ == "__main__":
    unittest.main()
