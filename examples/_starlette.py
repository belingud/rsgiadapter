import logging
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDenialResponse, WebSocketDisconnect

from rsgiadapter import ASGIToRSGI

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
)


@asynccontextmanager
async def lifespan(_app):
    print("lifespan start")
    yield
    print("lifespan stop")


async def hello(request: Request):
    return PlainTextResponse("Hello World!")


async def ws_echo(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(f"echo: {message}")
    except WebSocketDisconnect:
        pass


async def ws_deny(websocket: WebSocket):
    # exercises the websocket.http.response extension: the RSGI server only
    # carries the denial status, custom headers/body are dropped
    raise WebSocketDenialResponse(status_code=403, content="Denied")


application = Starlette(
    routes=[
        Route("/hello", hello),
        WebSocketRoute("/ws", ws_echo),
        WebSocketRoute("/ws-deny", ws_deny),
    ]
)

app = ASGIToRSGI(application, lifespan=lifespan)

if __name__ == "__main__":
    from granian import Granian

    server = Granian("_starlette:app")
    server.serve()
