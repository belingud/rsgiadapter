import io
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterable

from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from granian import Granian
from granian.constants import Interfaces
from starlette.responses import FileResponse

from rsgiadapter.asgi import ASGIToRSGI

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    print("lifespan startup")
    yield
    print("lifespan shutdown")


fast = FastAPI(lifespan=lifespan)


class Body(AsyncIterable):

    def __aiter__(self):
        return self

    def __init__(self, body: io.BytesIO, chunk_size=64 * 1024):
        self.chunk_size = chunk_size
        self.body = body

    async def __anext__(self):
        while True:
            chunk = self.body.read(self.chunk_size)
            if not chunk:
                raise StopAsyncIteration
            return chunk


@fast.get("/stream")
async def stream():
    b = io.BytesIO(b'{"hello": "world"}')
    b.seek(0)
    s = Body(b, chunk_size=2)
    return StreamingResponse(content=s)


@fast.get("/file")
async def file():
    return FileResponse("../README.md")


@fast.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"hello": "world"})
    await websocket.close()


app = ASGIToRSGI(fast, lifespan=lifespan)

if __name__ == "__main__":
    server = Granian(
        "_fastapi:app",
        address="127.0.0.1",
        port=8888,
        workers=1,
        interface=Interfaces.RSGI,
        reload=True,
    )
    server.serve()
