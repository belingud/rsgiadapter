"""
ASGI in-band lifespan support (server-driven startup/shutdown).

Kept for RSGI servers that drive the ASGI lifespan protocol: LifespanProtocol
speaks the server side of the ASGI lifespan handshake against an ASGI
application (startup/shutdown messages and their complete/failed replies).
Not wired into the adapter yet: ASGIToRSGI enters lifespans eagerly through
an asynccontextmanager and exits them at process shutdown.
"""

import asyncio
import logging


class LifespanProtocol:
    """
    Initialize the LifespanProtocol object.

    This constructor sets up the LifespanProtocol by initializing the event queue, startup and shutdown events,
    and setting up logging. It also initializes flags for unsupported operations, errors, and interrupt handling.

    Parameters:
        _callable: A callable object, typically representing an ASGI application.

    Attributes:
        _callable: ASGI application object.
        event_queue: An asyncio.Queue object for handling events.
        event_startup: An asyncio.Event object signaling the startup.
        event_shutdown: An asyncio.Event object signaling the shutdown.
        logger: A logging.Logger object for logging lifespan events.
        unsupported: A boolean flag indicating if the lifespan protocol is unsupported.
        errored: A boolean flag indicating if there has been an error in the lifespan protocol.
        failure_startup: A boolean flag indicating if there was a startup failure.
        failure_shutdown: A boolean flag indicating if there was a shutdown failure.
        exc: Stores any exception that has been caught during the lifespan protocol.
        state: A dictionary to hold any state information in the lifespan protocol.

    Returns:
        None
    """

    error_transition = "Invalid lifespan state transition"

    def __init__(self, _callable):
        self._callable = _callable
        self.event_queue = asyncio.Queue()
        self.event_startup = asyncio.Event()
        self.event_shutdown = asyncio.Event()
        self.logger = logging.getLogger("rsgiadapter.lifespan")
        self.unsupported = False
        self.errored = False
        self.failure_startup = False
        self.failure_shutdown = False
        self.exc = None
        self.state = {}

    async def handle(self, event):
        """
        Runs the lifespan ASGI callable for one phase and resolves its event.

        The event is only set once the application answered (or raised), so
        the phase awaiting it never returns before the handshake finished.
        """
        try:
            await self._callable(
                {
                    "type": "lifespan",
                    "asgi": {"version": "3.0", "spec_version": "2.3"},
                    "state": self.state,
                },
                self.receive,
                self.send,
            )
        except Exception as exc:
            self.errored = True
            self.exc = exc
            if self.failure_startup or self.failure_shutdown:
                return
            self.unsupported = True
            self.logger.warning("ASGI Lifespan errored.")
        finally:
            event.set()

    async def startup(self):
        """Sends ``lifespan.startup`` and waits for the application reply."""
        loop = asyncio.get_event_loop()
        _handler_task = loop.create_task(self.handle(self.event_startup))

        await self.event_queue.put({"type": "lifespan.startup"})
        await self.event_startup.wait()

        if self.errored:
            _handler_task.cancel()

    async def shutdown(self):
        """Sends ``lifespan.shutdown`` and waits for the application reply."""
        self.state.clear()

        if self.errored:
            return
        loop = asyncio.get_event_loop()
        _handler_task = loop.create_task(self.handle(self.event_shutdown))

        await self.event_queue.put({"type": "lifespan.shutdown"})
        await self.event_shutdown.wait()

        if self.errored:
            _handler_task.cancel()

    async def receive(self):
        return await self.event_queue.get()

    def _handle_startup_complete(self, message):
        assert not self.event_startup.is_set(), self.error_transition
        assert not self.event_shutdown.is_set(), self.error_transition
        self.event_startup.set()

    def _handle_startup_failed(self, message):
        assert not self.event_startup.is_set(), self.error_transition
        assert not self.event_shutdown.is_set(), self.error_transition
        self.event_startup.set()
        self.failure_startup = True
        if message.get("message"):
            self.logger.error(message["message"])

    def _handle_shutdown_complete(self, message):
        assert self.event_startup.is_set(), self.error_transition
        assert not self.event_shutdown.is_set(), self.error_transition
        self.event_shutdown.set()

    def _handle_shutdown_failed(self, message):
        assert self.event_startup.is_set(), self.error_transition
        assert not self.event_shutdown.is_set(), self.error_transition
        self.event_shutdown.set()
        self.failure_shutdown = True
        if message.get("message"):
            self.logger.error(message["message"])

    _event_handlers = {
        "lifespan.startup.complete": _handle_startup_complete,
        "lifespan.startup.failed": _handle_startup_failed,
        "lifespan.shutdown.complete": _handle_shutdown_complete,
        "lifespan.shutdown.failed": _handle_shutdown_failed,
    }

    async def send(self, message):
        handler = self._event_handlers[message["type"]]
        handler(self, message)
