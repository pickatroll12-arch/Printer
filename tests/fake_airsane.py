"""Servidor AirSane/eSCL simulado para las pruebas."""

from __future__ import annotations

import struct
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCANNER_PATH = "/canon_g2010_usb"

CAPABILITIES = """<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerCapabilities xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm"
    xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
  <pwg:MakeAndModel>Canon G2010 series</pwg:MakeAndModel>
  <scan:Platen><scan:PlatenInputCaps>
    <scan:MaxWidth>2551</scan:MaxWidth>
    <scan:MaxHeight>3508</scan:MaxHeight>
    <scan:SettingProfiles><scan:SettingProfile>
      <scan:ColorModes>
        <scan:ColorMode>RGB24</scan:ColorMode>
        <scan:ColorMode>Grayscale8</scan:ColorMode>
      </scan:ColorModes>
      <scan:DocumentFormats>
        <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
        <scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>
      </scan:DocumentFormats>
      <scan:SupportedResolutions><scan:DiscreteResolutions>
        <scan:DiscreteResolution>
          <scan:XResolution>75</scan:XResolution>
          <scan:YResolution>75</scan:YResolution>
        </scan:DiscreteResolution>
        <scan:DiscreteResolution>
          <scan:XResolution>300</scan:XResolution>
          <scan:YResolution>300</scan:YResolution>
        </scan:DiscreteResolution>
        <scan:DiscreteResolution>
          <scan:XResolution>600</scan:XResolution>
          <scan:YResolution>600</scan:YResolution>
        </scan:DiscreteResolution>
      </scan:DiscreteResolutions></scan:SupportedResolutions>
    </scan:SettingProfile></scan:SettingProfiles>
  </scan:PlatenInputCaps></scan:Platen>
</scan:ScannerCapabilities>
"""

STATUS = """<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerStatus xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm"
    xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
  <pwg:Version>2.6</pwg:Version>
  <pwg:State>Idle</pwg:State>
</scan:ScannerStatus>
"""

INDEX = f'<html><body><a href="{SCANNER_PATH}">Canon G2010 series</a>' \
        '<link href="/style.css"></body></html>'


def make_jpeg(width: int = 1240, height: int = 1754, components: int = 3,
              payload: bytes = b"\x00" * 128) -> bytes:
    """JPEG sintetico con marcadores validos (suficiente para SOF/DCTDecode)."""
    out = bytearray(b"\xff\xd8")
    out += b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00" + \
        struct.pack(">HH", 1, 1) + b"\x00\x00"
    sof = struct.pack(">BHHB", 8, height, width, components)
    for index in range(components):
        sof += bytes([index + 1, 0x11, 0])
    out += b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof
    out += b"\xff\xda" + struct.pack(">H", 8) + bytes([1, 1, 0, 0, 63, 0])
    out += payload
    out += b"\xff\xd9"
    return bytes(out)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # silencio en las pruebas
        return

    @property
    def state(self) -> "FakeAirSane":
        return self.server.state  # type: ignore[attr-defined]

    def _respond(self, status: int, body: bytes = b"",
                 content_type: str = "text/plain", headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        state = self.state
        state.requests.append(("GET", self.path))
        if state.down:
            self._respond(503, b"airsaned caido")
            return
        if self.path in ("/", ""):
            self._respond(200, INDEX.encode(), "text/html")
            return
        if self.path == SCANNER_PATH + "/ScannerCapabilities":
            self._respond(200, CAPABILITIES.encode(), "text/xml")
            return
        if self.path == SCANNER_PATH + "/ScannerStatus":
            self._respond(200, STATUS.encode(), "text/xml")
            return
        if self.path.endswith("/NextDocument"):
            job_id = self.path.split("/")[-2]
            if state.fail_next_document > 0:
                state.fail_next_document -= 1
                self._respond(500, b"fallo del escaner")
                return
            if state.jobs.get(job_id, 0) >= state.pages_per_job:
                self._respond(404, b"no hay mas paginas")
                return
            state.jobs[job_id] = state.jobs.get(job_id, 0) + 1
            self._respond(200, state.document, state.document_type)
            return
        self._respond(404, b"no encontrado")

    def do_POST(self):  # noqa: N802
        state = self.state
        state.requests.append(("POST", self.path))
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if state.down:
            self._respond(503, b"airsaned caido")
            return
        if self.path != SCANNER_PATH + "/ScanJobs":
            self._respond(404, b"no encontrado")
            return
        state.last_settings = body
        if state.scanjobs_status:
            status = state.scanjobs_status
            state.scanjobs_status = 0 if state.scanjobs_status_once else status
            self._respond(status, b"rechazado")
            return
        job_id = uuid.uuid4().hex[:8]
        state.jobs[job_id] = 0
        self._respond(201, b"", headers={
            "Location": f"http://{self.headers.get('Host')}{SCANNER_PATH}/ScanJobs/{job_id}"})

    def do_DELETE(self):  # noqa: N802
        self.state.requests.append(("DELETE", self.path))
        self._respond(200)


class FakeAirSane:
    """AirSane de mentira, con interruptores para provocar fallos."""

    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.state = self  # type: ignore[attr-defined]
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       args=(0.1,), daemon=True)
        self.jobs: dict[str, int] = {}
        self.requests: list[tuple[str, str]] = []
        self.document = make_jpeg()
        self.document_type = "image/jpeg"
        self.pages_per_job = 1
        self.fail_next_document = 0
        self.scanjobs_status = 0
        self.scanjobs_status_once = False
        self.down = False
        self.last_settings = b""

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeAirSane":
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
