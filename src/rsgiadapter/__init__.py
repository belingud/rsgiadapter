"""rsgiadapter: an ASGI to RSGI adapter.

Wrap an ASGI application with :class:`ASGIToRSGI` and serve it with an RSGI
server (e.g. granian with ``Interfaces.RSGI``).
"""

from rsgiadapter.asgi import ASGIToRSGI

__all__ = ["ASGIToRSGI"]

__version__ = "0.0.6"
