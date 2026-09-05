"""
Shared constants: the ASGI versions the adapter speaks and the message types
it understands (core HTTP/WebSocket events, ASGI extension events and the
extension messages the adapter consumes or drops at the RSGI boundary).
"""

from enum import StrEnum

# ASGI protocol versions announced in every scope handed to applications
DEFAULT_ASGI_VERSION = "3.0"
DEFAULT_SPEC_VERSION = "2.3"


class EventTypeEnum(StrEnum):
    """
    ASGI event types
    """

    # http
    HTTP_REQUEST = "http.request"
    HTTP_DISCONNECT = "http.disconnect"
    HTTP_RESP_START = "http.response.start"
    HTTP_RESP_END = "http.response.end"
    HTTP_RESP_BODY = "http.response.body"

    # websocket
    WEBSOCKET_CONNECT = "websocket.connect"
    WEBSOCKET_DISCONNECT = "websocket.disconnect"
    WEBSOCKET_RECEIVE = "websocket.receive"
    WEBSOCKET_SEND = "websocket.send"
    WEBSOCKET_ACCEPT = "websocket.accept"
    WEBSOCKET_CLOSE = "websocket.close"

    # http response extensions: pathsend is supported; the others cannot be
    # conveyed by RSGI servers yet and are only consumed/logged
    PATH_SEND = "http.response.pathsend"
    EARLY_HINT = "http.response.early_hint"
    HTTP_PUSH = "http.response.push"
    ZERO_COPY_SEND = "http.response.zerocopysend"
    TRAILERS = "http.response.trailers"
    HTTP_DEBUG = "http.response.debug"

    # websocket denial response extension
    WS_HTTP_RESP_START = "websocket.http.response.start"
    WS_HTTP_RESP_BODY = "websocket.http.response.body"
