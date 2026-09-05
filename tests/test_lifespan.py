import logging
import unittest

from rsgiadapter.lifespan import LifespanProtocol


class _ListHandler(logging.Handler):
    """Collects log records for assertions."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestLifespanProtocol(unittest.IsolatedAsyncioTestCase):
    """
    Exercises LifespanProtocol against fake ASGI applications speaking the
    server-driven lifespan handshake.

    The protocol runs the ASGI callable once per phase (startup, shutdown);
    each invocation is expected to consume one event from the queue and
    answer it through send().
    """

    async def test_startup_shutdown_happy_path(self):
        scope_seen = []
        state_seen = []

        async def app(scope, receive, send):
            scope_seen.append(scope)
            message = await receive()
            state_seen.append(scope["state"])
            await send({"type": f"{message['type']}.complete"})

        proto = LifespanProtocol(app)
        await proto.startup()
        self.assertFalse(proto.errored)
        self.assertFalse(proto.unsupported)
        self.assertFalse(proto.failure_startup)
        # the ASGI scope carries the lifespan type and the shared state dict
        self.assertEqual(scope_seen[0]["type"], "lifespan")
        self.assertEqual(
            scope_seen[0]["asgi"], {"version": "3.0", "spec_version": "2.3"}
        )
        # state mutated between the phases is what the app sees on shutdown
        proto.state["marker"] = "kept"
        await proto.shutdown()
        self.assertFalse(proto.failure_shutdown)
        self.assertIs(state_seen[0], state_seen[1])

    async def test_state_is_cleared_before_shutdown(self):
        async def app(scope, receive, send):
            message = await receive()
            if message["type"] == "lifespan.startup":
                scope["state"]["seen"] = True
                await send({"type": "lifespan.startup.complete"})
            else:
                # shutdown() clears the state dict before running the app again
                self.assertEqual(scope["state"], {})
                await send({"type": "lifespan.shutdown.complete"})

        proto = LifespanProtocol(app)
        await proto.startup()
        self.assertEqual(proto.state, {"seen": True})
        await proto.shutdown()
        self.assertEqual(proto.state, {})

    async def test_startup_failed_with_message(self):
        async def app(scope, receive, send):
            await receive()
            await send(
                {"type": "lifespan.startup.failed", "message": "cannot start"}
            )

        proto = LifespanProtocol(app)
        handler = _ListHandler()
        proto.logger.addHandler(handler)
        proto.logger.setLevel(logging.ERROR)
        try:
            await proto.startup()
        finally:
            proto.logger.removeHandler(handler)
        self.assertTrue(proto.failure_startup)
        self.assertIn("cannot start", handler.records[0].getMessage())

    async def test_startup_failed_without_message(self):
        async def app(scope, receive, send):
            await receive()
            await send({"type": "lifespan.startup.failed"})

        proto = LifespanProtocol(app)
        handler = _ListHandler()
        proto.logger.addHandler(handler)
        proto.logger.setLevel(logging.ERROR)
        try:
            await proto.startup()
        finally:
            proto.logger.removeHandler(handler)
        self.assertTrue(proto.failure_startup)
        # no message payload: the handler logs nothing
        self.assertEqual(handler.records, [])

    async def test_shutdown_failed_with_message(self):
        async def app(scope, receive, send):
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            else:
                self.assertEqual(message["type"], "lifespan.shutdown")
                await send(
                    {"type": "lifespan.shutdown.failed", "message": "cannot stop"}
                )

        proto = LifespanProtocol(app)
        await proto.startup()
        handler = _ListHandler()
        proto.logger.addHandler(handler)
        proto.logger.setLevel(logging.ERROR)
        try:
            await proto.shutdown()
        finally:
            proto.logger.removeHandler(handler)
        self.assertTrue(proto.failure_shutdown)
        self.assertIn("cannot stop", handler.records[0].getMessage())

    async def test_app_raising_marks_lifespan_unsupported(self):
        async def app(scope, receive, send):
            await receive()
            raise RuntimeError("no lifespan support")

        proto = LifespanProtocol(app)
        handler = _ListHandler()
        proto.logger.addHandler(handler)
        proto.logger.setLevel(logging.WARNING)
        try:
            await proto.startup()
        finally:
            proto.logger.removeHandler(handler)
        self.assertTrue(proto.errored)
        self.assertTrue(proto.unsupported)
        self.assertIsInstance(proto.exc, RuntimeError)
        self.assertIn("ASGI Lifespan errored.", handler.records[0].getMessage())
        # errored protocols skip the shutdown handshake
        await proto.shutdown()

    async def test_exception_after_startup_failed_keeps_failure_flag(self):
        async def app(scope, receive, send):
            await receive()
            await send({"type": "lifespan.startup.failed"})
            raise RuntimeError("crash after reporting failure")

        proto = LifespanProtocol(app)
        await proto.startup()
        self.assertTrue(proto.errored)
        self.assertTrue(proto.failure_startup)
        # a failure was already reported: do not mark the protocol unsupported
        self.assertFalse(proto.unsupported)

    async def test_invalid_state_transitions(self):
        async def app(scope, receive, send):
            message = await receive()
            await send({"type": f"{message['type']}.complete"})

        proto = LifespanProtocol(app)
        # shutdown.complete before startup.complete is an invalid transition
        with self.assertRaises(AssertionError):
            await proto.send({"type": "lifespan.shutdown.complete"})
        await proto.startup()
        # startup.complete twice is an invalid transition
        with self.assertRaises(AssertionError):
            await proto.send({"type": "lifespan.startup.complete"})
        await proto.shutdown()
        # shutdown.complete twice is an invalid transition
        with self.assertRaises(AssertionError):
            await proto.send({"type": "lifespan.shutdown.complete"})

    async def test_raise_after_complete_still_cancels_handler_task(self):
        # the application answers the phase and then raises: the protocol
        # must still notice the error and cancel its handler task
        calls = []

        async def app(scope, receive, send):
            calls.append("run")
            await receive()
            await send({"type": "lifespan.startup.complete"})
            raise RuntimeError("crash after startup")

        proto = LifespanProtocol(app)
        await proto.startup()
        self.assertTrue(proto.errored)
        self.assertTrue(proto.unsupported)
        self.assertEqual(calls, ["run"])
        # errored shutdown is skipped
        await proto.shutdown()

    async def test_raise_during_shutdown_phase(self):
        # second invocation (shutdown) raises after answering
        calls = []

        async def app(scope, receive, send):
            calls.append("run")
            message = await receive()
            await send({"type": f"{message['type']}.complete"})
            if message["type"] == "lifespan.shutdown":
                raise RuntimeError("crash during shutdown")

        proto = LifespanProtocol(app)
        await proto.startup()
        self.assertFalse(proto.errored)
        await proto.shutdown()
        self.assertTrue(proto.errored)
        self.assertEqual(calls, ["run", "run"])

    async def test_unknown_message_raises_key_error(self):
        proto = LifespanProtocol(lambda *args: None)
        with self.assertRaises(KeyError):
            await proto.send({"type": "lifespan.unknown"})

    async def test_receive_drains_queued_events(self):
        proto = LifespanProtocol(lambda *args: None)
        await proto.event_queue.put({"type": "lifespan.startup"})
        message = await proto.receive()
        self.assertEqual(message, {"type": "lifespan.startup"})


if __name__ == "__main__":
    unittest.main()
