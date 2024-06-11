# rsgiadapter

[![PyPI - Version](https://img.shields.io/pypi/v/rsgiadapter?style=for-the-badge)](https://pypi.org/project/rsgiadapter/) ![GitHub License](https://img.shields.io/github/license/belingud/rsgiadapter?style=for-the-badge) ![PyPI - Downloads](https://img.shields.io/pypi/dm/rsgiadapter?logo=pypi&cacheSeconds=86400&style=for-the-badge) ![PyPI - Status](https://img.shields.io/pypi/status/rsgiadapter?style=for-the-badge)

An Asgi to rsgi adapter.

RSGI Specification ref: https://github.com/emmett-framework/granian/blob/master/docs/spec/RSGI.md

`rsgiadapter` is an adapter for [RSGI](https://github.com/emmett-framework/granian/blob/master/docs/spec/RSGI.md) server run [ASGI](https://asgi.readthedocs.io) application like FastAPI and BlackSheep.

Usage:

`app.py`
```python
import granian
from granian.constants import Interfaces
from rsgiadapter import ASGIToRSGI

app = None  # Define your asgi application here

rsgi_app = ASGIToRSGI(app)

serve = granian.Granian("app:rsgi_app", interface=Interfaces.RSGI)
serve.serve()
```

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
  - [x] lifespan.startup.complete
  - [x] lifespan.startup.failed
  - [x] lifespan.shutdown
  - [x] lifespan.shutdown.complete
  - [x] lifespan.shutdown.failed

Ref:

- Granian: https://github.com/emmett-framework/granian
