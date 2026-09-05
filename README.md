# rsgiadapter

[![PyPI - Version](https://img.shields.io/pypi/v/rsgiadapter?style=for-the-badge)](https://pypi.org/project/rsgiadapter/) ![GitHub License](https://img.shields.io/github/license/belingud/rsgiadapter?style=for-the-badge) ![PyPI - Downloads](https://img.shields.io/pypi/dm/rsgiadapter?logo=pypi&cacheSeconds=86400&style=for-the-badge) ![PyPI - Status](https://img.shields.io/pypi/status/rsgiadapter?style=for-the-badge)
![Pepy Total Downlods](https://img.shields.io/pepy/dt/rsgiadapter?style=for-the-badge&logo=python)

An Asgi to rsgi adapter.

RSGI Specification ref: https://github.com/emmett-framework/granian/blob/master/docs/spec/RSGI.md

`rsgiadapter` is an adapter for [RSGI](https://github.com/emmett-framework/granian/blob/master/docs/spec/RSGI.md) server run [ASGI](https://asgi.readthedocs.io) application like FastAPI and BlackSheep.

This project provides a way to run ASGI web frameworks on an RSGI server, but it is not recommended to use the RSGI server in this manner. Using frameworks that natively support the RSGI protocol can better leverage the performance advantages of RSGI.

Check [examples](https://github.com/belingud/rsgiadapter/tree/master/examples) for more framework examples.
You can run the scripts in the examples directory to test.

Basic Usage:

`app.py`
```python
import granian
from granian.constants import Interfaces
from rsgiadapter import ASGIToRSGI


# Declare your asgi application here
async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send(
        {"type": "http.response.body", "body": b"Hello, World!", "more_body": False}
    )


rsgi_app = ASGIToRSGI(app)

if __name__ == "__main__":
    serve = granian.Granian("app:rsgi_app", interface=Interfaces.RSGI)
    serve.serve()
```

with asgi lifespan:

```python
from contextlib import asynccontextmanager

import granian
from granian.constants import Interfaces
from rsgiadapter import ASGIToRSGI


@asynccontextmanager
async def lifespan(_app):
    print("lifespan start")
    yield
    print("lifespan stop")


# Declare your asgi application here
async def app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send(
        {"type": "http.response.body", "body": b"Hello, World!", "more_body": False}
    )


rsgi_app = ASGIToRSGI(app, lifespan=lifespan)

if __name__ == "__main__":
    serve = granian.Granian("app:rsgi_app", interface=Interfaces.RSGI)
    serve.serve()
```

Supported Framework:

1. FastAPI
2. Starlette
3. litestar
4. falcon
5. blacksheep
6. quart
7. sanic
8. Django>=3.0
9. and other Python web frameworks that support the ASGI protocol, with or without lifespan support.

Supported Feature:

- [x] HTTP Request Response
  - [x] ASGI scope
  - [x] ASGI receive
  - [x] ASGI send
- [x] WebSocket Request Response
  - [x] ASGI scope
  - [x] websocket.connect
  - [x] websocket.accept
  - [x] websocket.receive
  - [x] websocket.send
  - [x] websocket.close
- [x] Lifespan
  - [x] lifespan.startup
  - [x] lifespan.startup.complete(silence)
  - [x] lifespan.startup.failed(will terminate)
  - [x] lifespan.shutdown
  - [x] lifespan.shutdown.complete(silence)
  - [x] lifespan.shutdown.failed(will terminate)
- [x] Extensions
  - [x] http.response.pathsend
  - [x] websocket.http.response
  - [x] http.response.debug (only logged by the adapter, not sent to the wire)
  - [ ] http.response.push (requires RSGI server support)
  - [ ] http.response.zerocopysend (requires RSGI server support)
  - [ ] http.response.early_hint (requires RSGI server support)
  - [ ] http.response.trailers (requires RSGI server support)

> Unsupported HTTP extensions are not advertised in `scope["extensions"]`, so
> ASGI frameworks will not attempt to use them; if an application sends such a
> message anyway, the adapter consumes it without breaking the response and
> logs a warning. The RSGI protocol exposed by granian (RSGI spec 1.6) has no
> transport for server push, zero-copy sends, 103 early hints or response
> trailers, and granian's native ASGI support does not implement them either.
>
> WebSocket caveats imposed by the RSGI server: the selected subprotocol
> cannot be negotiated, `websocket.close` codes/reasons are dropped
> (see [granian #645](https://github.com/emmett-framework/granian/issues/645)),
> and a denial response (`websocket.http.response`) only carries its status
> code - custom headers and body cannot cross the RSGI boundary yet.

Ref:

- Granian: https://github.com/emmett-framework/granian
