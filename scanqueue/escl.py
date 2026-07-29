"""Cliente eSCL minimo contra AirSane (sin dependencias externas).

AirSane ya mantiene abierto el dispositivo USB, asi que escaneamos a traves de
su API eSCL en lugar de pelearnos con SANE por el mismo /dev/bus/usb.

Flujo eSCL:
    POST {scanner}/ScanJobs      -> 201 + cabecera Location
    GET  {location}/NextDocument -> 200 con la imagen (404 = no hay mas paginas)
    DELETE {location}            -> libera el trabajo en el escaner
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Iterable

from .models import PAGE_SIZES

LOG = logging.getLogger("scanqueue.escl")

USER_AGENT = "scanqueue/1.0 (+eSCL)"
_HREF_RE = re.compile(rb'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_STATIC_SUFFIXES = (".css", ".js", ".png", ".jpg", ".jpeg", ".ico", ".svg", ".gif", ".xml")

# Las peticiones van siempre a localhost: cualquier proxy configurado en el
# entorno (http_proxy/HTTPS_PROXY) romperia la conexion.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ESCLError(RuntimeError):
    """Error de protocolo o de transporte hablando con AirSane."""

    def __init__(self, message: str, *, status: int | None = None,
                 retryable: bool = True) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class ESCLTimeout(ESCLError):
    """El escaner no respondio a tiempo."""


@dataclass
class HTTPResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)


def http_request(url: str, *, method: str = "GET", data: bytes | None = None,
                 headers: dict[str, str] | None = None, timeout: float = 10.0
                 ) -> HTTPResponse:
    """Peticion HTTP simple. Las respuestas 4xx/5xx se devuelven, no lanzan."""
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return HTTPResponse(
                status=response.status,
                headers={k.lower(): v for k, v in response.headers.items()},
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:  # 4xx/5xx: informacion util, no fatal
        body = b""
        try:
            body = exc.read()
        except Exception:  # pragma: no cover - el cuerpo es opcional
            pass
        return HTTPResponse(
            status=exc.code,
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            body=body,
        )
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise ESCLTimeout(f"timeout hablando con {url}: {reason}") from exc
        raise ESCLError(f"no se pudo conectar con {url}: {reason}") from exc
    except TimeoutError as exc:
        raise ESCLTimeout(f"timeout hablando con {url}") from exc
    except OSError as exc:
        raise ESCLError(f"error de red con {url}: {exc}") from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _iter_text(root: ET.Element, name: str) -> Iterable[str]:
    target = name.lower()
    for element in root.iter():
        if _local(element.tag) == target and element.text:
            yield element.text.strip()


@dataclass
class Capabilities:
    """Subconjunto util de ScannerCapabilities."""

    make_and_model: str = ""
    formats: set[str] = field(default_factory=set)
    color_modes: set[str] = field(default_factory=set)
    resolutions: set[int] = field(default_factory=set)
    max_width: int = 0
    max_height: int = 0
    raw_bytes: int = 0

    def supports_format(self, mime: str) -> bool:
        # Si el escaner no declara formatos, asumimos que acepta lo que pidamos.
        return not self.formats or mime.lower() in self.formats

    def supports_mode(self, mode: str) -> bool:
        return not self.color_modes or mode.lower() in {m.lower() for m in self.color_modes}

    def closest_resolution(self, dpi: int) -> int:
        if not self.resolutions:
            return dpi
        if dpi in self.resolutions:
            return dpi
        return min(self.resolutions, key=lambda value: (abs(value - dpi), value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "make_and_model": self.make_and_model,
            "formats": sorted(self.formats),
            "color_modes": sorted(self.color_modes),
            "resolutions": sorted(self.resolutions),
            "max_width": self.max_width,
            "max_height": self.max_height,
        }


def parse_capabilities(payload: bytes) -> Capabilities:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ESCLError(f"ScannerCapabilities no es XML valido: {exc}") from exc

    caps = Capabilities(raw_bytes=len(payload))
    for value in _iter_text(root, "MakeAndModel"):
        caps.make_and_model = value
        break
    for element in root.iter():
        tag = _local(element.tag)
        text = (element.text or "").strip()
        if not text:
            continue
        if tag in ("documentformat", "documentformatext"):
            caps.formats.add(text.lower())
        elif tag == "colormode":
            caps.color_modes.add(text)
        elif tag in ("xresolution", "yresolution"):
            if text.isdigit():
                caps.resolutions.add(int(text))
        elif tag == "maxwidth" and text.isdigit():
            caps.max_width = max(caps.max_width, int(text))
        elif tag == "maxheight" and text.isdigit():
            caps.max_height = max(caps.max_height, int(text))
    return caps


def build_scan_settings(*, dpi: int, mime: str, color_mode: str, source: str,
                        region: tuple[int, int] | None = None) -> bytes:
    """Genera el XML ScanSettings de la peticion."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<scan:ScanSettings '
        'xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" '
        'xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">',
        "<pwg:Version>2.6</pwg:Version>",
    ]
    if region:
        width, height = region
        parts += [
            '<pwg:ScanRegions pwg:MustHonor="false"><pwg:ScanRegion>',
            "<pwg:XOffset>0</pwg:XOffset>",
            "<pwg:YOffset>0</pwg:YOffset>",
            f"<pwg:Width>{int(width)}</pwg:Width>",
            f"<pwg:Height>{int(height)}</pwg:Height>",
            "<pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches"
            "</pwg:ContentRegionUnits>",
            "</pwg:ScanRegion></pwg:ScanRegions>",
        ]
    parts += [
        f"<pwg:InputSource>{source}</pwg:InputSource>",
        f"<scan:ColorMode>{color_mode}</scan:ColorMode>",
        f"<scan:XResolution>{int(dpi)}</scan:XResolution>",
        f"<scan:YResolution>{int(dpi)}</scan:YResolution>",
        f"<pwg:DocumentFormat>{mime}</pwg:DocumentFormat>",
        f"<scan:DocumentFormatExt>{mime}</scan:DocumentFormatExt>",
        "</scan:ScanSettings>",
    ]
    return "".join(parts).encode("utf-8")


def region_for_page(page: str, caps: Capabilities | None) -> tuple[int, int] | None:
    """Region en 1/300 de pulgada, recortada a lo que soporte el escaner."""
    if not page:
        return None
    width, height = PAGE_SIZES[page]
    if caps and caps.max_width and caps.max_height:
        width = min(width, caps.max_width)
        height = min(height, caps.max_height)
    return width, height


class ESCLClient:
    """Cliente para un servidor AirSane con uno o varios escaneres."""

    def __init__(self, base_url: str, *, scanner: str = "", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.scanner = scanner.strip("/")
        self.timeout = timeout
        self._scanner_url: str | None = None
        self._caps: Capabilities | None = None

    # ---------------------------------------------------------------- descubrir

    def _candidate_urls(self) -> list[str]:
        if self.scanner:
            explicit = self.scanner
            if explicit.startswith("http://") or explicit.startswith("https://"):
                return [explicit.rstrip("/")]
            return [f"{self.base_url}/{explicit.strip('/')}"]

        candidates: list[str] = []
        try:
            response = http_request(self.base_url + "/", timeout=self.timeout)
        except ESCLError:
            return [self.base_url]
        if response.status == 200:
            for match in _HREF_RE.findall(response.body):
                href = match.decode("utf-8", "replace").strip()
                if not href or href.startswith(("#", "mailto:", "javascript:")):
                    continue
                if href.lower().endswith(_STATIC_SUFFIXES):
                    continue
                url = urllib.parse.urljoin(self.base_url + "/", href).rstrip("/")
                if url.startswith(self.base_url) and url != self.base_url and url not in candidates:
                    candidates.append(url)
        candidates.append(self.base_url)
        return candidates

    def resolve_scanner(self, force: bool = False) -> str:
        """Devuelve la URL base del escaner, descubriendola si hace falta."""
        if self._scanner_url and not force:
            return self._scanner_url

        errors: list[str] = []
        for candidate in self._candidate_urls():
            for suffix in ("/ScannerCapabilities", "/eSCL/ScannerCapabilities"):
                url = candidate + suffix
                try:
                    response = http_request(url, timeout=self.timeout)
                except ESCLError as exc:
                    errors.append(f"{url}: {exc}")
                    continue
                if response.status != 200 or b"ScannerCapabilities" not in response.body:
                    errors.append(f"{url}: HTTP {response.status}")
                    continue
                self._scanner_url = candidate + suffix[: -len("/ScannerCapabilities")]
                self._caps = parse_capabilities(response.body)
                LOG.info("escaner eSCL resuelto en %s (%s)", self._scanner_url,
                         self._caps.make_and_model or "modelo desconocido")
                return self._scanner_url

        raise ESCLError(
            "no se encontro ningun escaner eSCL en " + self.base_url +
            (f" ({errors[0]})" if errors else ""))

    def capabilities(self, force: bool = False) -> Capabilities:
        if self._caps is None or force:
            scanner_url = self.resolve_scanner(force=force)
            if self._caps is None:
                response = http_request(scanner_url + "/ScannerCapabilities",
                                        timeout=self.timeout)
                if response.status != 200:
                    raise ESCLError(f"ScannerCapabilities devolvio HTTP {response.status}",
                                    status=response.status)
                self._caps = parse_capabilities(response.body)
        return self._caps

    def invalidate(self) -> None:
        """Olvida el escaner descubierto (tras un reinicio de airsaned)."""
        self._scanner_url = None
        self._caps = None

    # --------------------------------------------------------------- estado

    def status(self) -> dict[str, str]:
        scanner_url = self.resolve_scanner()
        response = http_request(scanner_url + "/ScannerStatus", timeout=self.timeout)
        if response.status != 200:
            raise ESCLError(f"ScannerStatus devolvio HTTP {response.status}",
                            status=response.status)
        try:
            root = ET.fromstring(response.body)
        except ET.ParseError as exc:
            raise ESCLError(f"ScannerStatus no es XML valido: {exc}") from exc
        out: dict[str, str] = {}
        for value in _iter_text(root, "State"):
            out["state"] = value
            break
        for value in _iter_text(root, "Version"):
            out["version"] = value
            break
        return out

    # --------------------------------------------------------------- escanear

    def start_job(self, settings: bytes, *, timeout: float | None = None) -> str:
        """Crea un trabajo eSCL y devuelve la URL del trabajo (Location)."""
        scanner_url = self.resolve_scanner()
        response = http_request(
            scanner_url + "/ScanJobs",
            method="POST",
            data=settings,
            headers={"Content-Type": "text/xml", "Expect": ""},
            timeout=timeout or self.timeout,
        )
        if response.status in (200, 201):
            location = response.header("location")
            if not location:
                raise ESCLError("ScanJobs no devolvio cabecera Location")
            return urllib.parse.urljoin(scanner_url + "/", location).rstrip("/")
        if response.status == 409:
            raise ESCLError("el escaner esta ocupado (HTTP 409)", status=409)
        if response.status in (400, 415):
            # Ajustes rechazados: reintentar con los mismos parametros no sirve.
            detail = response.body[:200].decode("utf-8", "replace").strip()
            raise ESCLError(
                f"el escaner rechazo los ajustes (HTTP {response.status}): {detail}",
                status=response.status, retryable=False)
        raise ESCLError(f"ScanJobs devolvio HTTP {response.status}", status=response.status)

    def next_document(self, job_url: str, *, timeout: float) -> bytes | None:
        """Descarga la siguiente pagina. None cuando ya no quedan paginas."""
        response = http_request(job_url + "/NextDocument", timeout=timeout)
        if response.status == 200:
            if not response.body:
                raise ESCLError("NextDocument devolvio un documento vacio")
            return response.body
        if response.status in (404, 410):
            return None
        if response.status == 503:
            raise ESCLError("el escaner no esta disponible (HTTP 503)", status=503)
        raise ESCLError(f"NextDocument devolvio HTTP {response.status}",
                        status=response.status)

    def cancel_job(self, job_url: str) -> None:
        """Mejor esfuerzo: liberar el trabajo en el escaner."""
        try:
            http_request(job_url, method="DELETE", timeout=self.timeout)
        except ESCLError as exc:
            LOG.debug("no se pudo cancelar el trabajo eSCL %s: %s", job_url, exc)

    def scan(self, *, dpi: int, mime: str, color_mode: str, source: str,
             page: str = "", deadline: float | None = None,
             max_pages: int = 1) -> list[bytes]:
        """Escaneo completo. Devuelve las paginas obtenidas."""
        caps = None
        try:
            caps = self.capabilities()
        except ESCLError as exc:
            LOG.warning("no se pudieron leer las capacidades, se usan los "
                        "parametros tal cual: %s", exc)

        effective_dpi = caps.closest_resolution(dpi) if caps else dpi
        if caps and effective_dpi != dpi:
            LOG.info("el escaner no soporta %s ppp; se usara %s ppp", dpi, effective_dpi)

        settings = build_scan_settings(
            dpi=effective_dpi, mime=mime, color_mode=color_mode, source=source,
            region=region_for_page(page, caps))

        remaining = max(5.0, (deadline - time.time())) if deadline else self.timeout
        job_url = self.start_job(settings, timeout=min(remaining, 60.0))
        LOG.debug("trabajo eSCL creado: %s", job_url)

        pages: list[bytes] = []
        try:
            while len(pages) < max_pages:
                remaining = (deadline - time.time()) if deadline else self.timeout * 6
                if remaining <= 0:
                    raise ESCLTimeout("se agoto el tiempo del trabajo esperando al escaner")
                document = self.next_document(job_url, timeout=remaining)
                if document is None:
                    break
                pages.append(document)
        except BaseException:
            self.cancel_job(job_url)
            raise

        if not pages:
            raise ESCLError("el escaner no devolvio ninguna pagina")
        return pages
