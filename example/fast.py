import io
from typing import AsyncIterable

from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from granian import Granian
from granian.constants import Interfaces
from starlette.responses import FileResponse

from rsgiadapter.asgi import ASGIToRSGI

fast = FastAPI()


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


app = ASGIToRSGI(fast)

if __name__ == "__main__":
    server = Granian(
        "fast:app",
        address="127.0.0.1",
        port=8888,
        workers=1,
        interface=Interfaces.RSGI,
        reload=True,
    )
    server.serve()
