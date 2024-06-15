# rsgiadapter

[![PyPI - Version](https://img.shields.io/pypi/v/rsgiadapter?style=for-the-badge)](https://pypi.org/project/rsgiadapter/) ![GitHub License](https://img.shields.io/github/license/belingud/rsgiadapter?style=for-the-badge) ![PyPI - Downloads](https://img.shields.io/pypi/dm/rsgiadapter?logo=pypi&cacheSeconds=86400&style=for-the-badge) ![PyPI - Status](https://img.shields.io/pypi/status/rsgiadapter?style=for-the-badge)

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
- [x] Extensions
  - [x] http.response.pathsend
  - [ ] websocket.http.response
  - [ ] http.response.push
  - [ ] http.response.zerocopysend
  - [ ] http.response.early_hint
  - [ ] http.response.trailers
  - [ ] http.response.debug
- [x] Lifespan
  - [x] lifespan.startup
  - [x] lifespan.startup.complete(silence)
  - [x] lifespan.startup.failed(will terminate)
  - [x] lifespan.shutdown
  - [x] lifespan.shutdown.complete(silence)
  - [x] lifespan.shutdown.failed(will terminate)

Ref:

- Granian: https://github.com/emmett-framework/granian
