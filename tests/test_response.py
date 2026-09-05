import unittest
from unittest.mock import MagicMock

from rsgiadapter.response import BodyManager, Response


class TestAppendMethod(unittest.TestCase):

    def setUp(self):
        self.body = BodyManager()

    def test_append_bytes(self):
        data = b"test"
        self.body.append(data)
        self.assertEqual(self.body.get_body(), data)

    def test_append_string(self):
        data = "test"
        self.body.append(data)
        self.assertEqual(self.body.get_body(), data.encode("utf-8"))

    def test_append_unsupported_type(self):
        with self.assertWarns(ResourceWarning):
            data = 123  # unsupported type
            self.body.append(data)

    def test_body_length_incremented(self):
        data = b"test"
        self.body.append(data)
        self.assertEqual(self.body._body_length, 1)

    def test_chunk_size_updated(self):
        data = b"test"
        self.body.append(data)
        self.assertEqual(self.body.chunk_size, len(data))

    def test_closed_body_cleared(self):
        self.body._body.close()
        self.body._body = MagicMock()
        self.body.clear_body()
        self.assertEqual(self.body._body_length, 0)


class TestBodyManagerIteration(unittest.TestCase):
    """sync/async iteration and lifecycle of BodyManager"""

    def setUp(self):
        self.body = BodyManager(chunk_size=3)
        for chunk in (b"aaa", b"bbb", b"ccc"):
            self.body.append(chunk)

    def test_len_tracks_chunks(self):
        self.assertEqual(len(self.body), 3)

    def test_sync_iteration_yields_chunks(self):
        # iteration starts from the beginning every time
        self.assertEqual(list(self.body), [b"aaa", b"bbb", b"ccc"])
        self.assertEqual(list(self.body), [b"aaa", b"bbb", b"ccc"])

    def test_sync_iteration_raises_stop_iteration_when_exhausted(self):
        iterator = iter(self.body)
        list(iterator)  # consume everything
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_async_iteration_yields_chunks(self):
        async def collect():
            return [chunk async for chunk in self.body]

        import asyncio

        self.assertEqual(asyncio.run(collect()), [b"aaa", b"bbb", b"ccc"])

    def test_closed_flag(self):
        self.assertFalse(self.body.closed)
        self.body._body.close()
        self.assertTrue(self.body.closed)

    def test_get_body_after_close_returns_empty(self):
        body = BodyManager()
        body.append(b"data")
        body._body.close()
        self.assertEqual(body.get_body(), b"")

    def test_destructor_closes_backing_file(self):
        body = BodyManager()
        body.append(b"data")
        body.__del__()
        self.assertTrue(body.closed)
        # double destruction is harmless
        body.__del__()

    def test_destructor_suppresses_close_errors(self):
        body = BodyManager()
        body._body = MagicMock(closed=False)
        body._body.close.side_effect = OSError("cannot close")
        body.__del__()  # must not raise

    def test_get_body_joins_chunks(self):
        self.assertEqual(self.body.get_body(), b"aaabbbccc")


class TestResponse(unittest.TestCase):

    def test_get_body_and_clear_body(self):
        response = Response(status=200)
        response.body.append(b"hello")
        self.assertEqual(response.get_body(), b"hello")
        response.clear_body()
        self.assertEqual(len(response.body), 0)


if __name__ == "__main__":
    unittest.main()
