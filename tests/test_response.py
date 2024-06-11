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
