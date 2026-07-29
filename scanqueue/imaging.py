"""Utilidades de imagen sin dependencias externas.

Lo unico que necesitamos de verdad es envolver un JPEG en un PDF cuando AirSane
no puede generar PDF directamente. Se hace con un escritor PDF minimo que
embebe el JPEG tal cual (filtro DCTDecode), sin recomprimir: rapido y sin
Pillow, algo que se agradece en un Core 2 Duo.
"""

from __future__ import annotations

import logging
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

LOG = logging.getLogger("scanqueue.imaging")

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PDF_MAGIC = b"%PDF"
TIFF_MAGICS = (b"II*\x00", b"MM\x00*")

# Marcadores SOF que describen tamaño y componentes (se excluyen DHT/DAC/RSTn).
_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


class ImagingError(RuntimeError):
    """No se pudo interpretar o convertir la imagen."""


def sniff_format(data: bytes) -> str:
    """Detecta el formato real de los bytes devueltos por el escaner."""
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    if data.startswith(PNG_MAGIC):
        return "png"
    if data.startswith(PDF_MAGIC):
        return "pdf"
    if data[:4] in TIFF_MAGICS:
        return "tiff"
    return "unknown"


def jpeg_info(data: bytes) -> tuple[int, int, int]:
    """Devuelve (ancho, alto, componentes) leyendo los marcadores JPEG."""
    if not data.startswith(JPEG_MAGIC):
        raise ImagingError("los datos no son un JPEG")
    offset = 2
    size = len(data)
    while offset + 3 < size:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:  # fin de imagen
            break
        if offset + 2 > size:
            break
        (segment_length,) = struct.unpack(">H", data[offset:offset + 2])
        if segment_length < 2:
            raise ImagingError("segmento JPEG corrupto")
        if marker in _SOF_MARKERS:
            if offset + 8 > size:
                raise ImagingError("cabecera SOF JPEG truncada")
            height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            components = data[offset + 7]
            if not width or not height:
                raise ImagingError("dimensiones JPEG invalidas")
            return width, height, components
        offset += segment_length
    raise ImagingError("no se encontro la cabecera SOF del JPEG")


def _pdf_escape_stream(objects: list[bytes]) -> bytes:
    """Ensambla objetos PDF ya serializados con su tabla xref."""
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n"
            f"{xref_offset}\n%%EOF\n").encode("ascii")
    return bytes(out)


def jpeg_to_pdf(pages: list[bytes], dpi: int = 300) -> bytes:
    """Envuelve uno o varios JPEG en un PDF sin recomprimir."""
    if not pages:
        raise ImagingError("no hay paginas que convertir a PDF")
    dpi = max(1, int(dpi))

    page_objects: list[bytes] = []
    image_objects: list[bytes] = []
    content_objects: list[bytes] = []
    media_boxes: list[tuple[float, float]] = []

    for data in pages:
        width, height, components = jpeg_info(data)
        colorspace = {1: b"/DeviceGray", 3: b"/DeviceRGB", 4: b"/DeviceCMYK"}.get(components)
        if colorspace is None:
            raise ImagingError(f"JPEG con {components} componentes no soportado")
        decode = b" /Decode [1 0 1 0 1 0 1 0]" if components == 4 else b""
        pt_width = width * 72.0 / dpi
        pt_height = height * 72.0 / dpi
        media_boxes.append((pt_width, pt_height))
        image_objects.append(
            b"<< /Type /XObject /Subtype /Image /Width " + str(width).encode() +
            b" /Height " + str(height).encode() + b" /ColorSpace " + colorspace +
            b" /BitsPerComponent 8 /Filter /DCTDecode" + decode +
            b" /Length " + str(len(data)).encode() + b" >>\nstream\n" + data +
            b"\nendstream")
        stream = (f"q {pt_width:.2f} 0 0 {pt_height:.2f} 0 0 cm /Im0 Do Q\n"
                  ).encode("ascii")
        content_objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream +
            b"endstream")

    # Numeracion: 1=catalogo, 2=pages, luego (page, image, content) por hoja.
    page_ids = [3 + index * 3 for index in range(len(pages))]
    kids = b" ".join(f"{pid} 0 R".encode("ascii") for pid in page_ids)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " +
        str(len(pages)).encode() + b" >>",
    ]
    for index, page_id in enumerate(page_ids):
        pt_width, pt_height = media_boxes[index]
        page_objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " +
            f"{pt_width:.2f} {pt_height:.2f}".encode("ascii") +
            b"] /Resources << /XObject << /Im0 " + str(page_id + 1).encode() +
            b" 0 R >> >> /Contents " + str(page_id + 2).encode() + b" 0 R >>")
        objects += [page_objects[-1], image_objects[index], content_objects[index]]
    return _pdf_escape_stream(objects)


def _external_converter() -> list[str] | None:
    for candidate in (["magick"], ["convert"], ["gm", "convert"]):
        if shutil.which(candidate[0]):
            return candidate
    return None


def convert_with_external_tool(data: bytes, source_ext: str, target_ext: str,
                               timeout: float = 120.0) -> bytes:
    """Convierte usando ImageMagick/GraphicsMagick si estan instalados."""
    tool = _external_converter()
    if tool is None:
        raise ImagingError(
            f"no se puede convertir {source_ext} -> {target_ext}: instala "
            f"imagemagick, o pide un formato que soporte el escaner")
    with tempfile.TemporaryDirectory(prefix="scanqueue-conv-") as tmp:
        src = Path(tmp) / f"in.{source_ext}"
        dst = Path(tmp) / f"out.{target_ext}"
        src.write_bytes(data)
        command = [*tool, str(src), str(dst)]
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout,
                                    check=False)
        except subprocess.TimeoutExpired as exc:
            raise ImagingError(f"la conversion con {tool[0]} excedio {timeout}s") from exc
        except OSError as exc:
            raise ImagingError(f"no se pudo ejecutar {tool[0]}: {exc}") from exc
        if result.returncode != 0 or not dst.exists():
            detail = result.stderr[:200].decode("utf-8", "replace").strip()
            raise ImagingError(f"{tool[0]} fallo (codigo {result.returncode}): {detail}")
        return dst.read_bytes()


def coerce_format(pages: list[bytes], target: str, dpi: int) -> bytes:
    """Lleva las paginas escaneadas al formato pedido.

    `target` es una extension normalizada: pdf, jpg, png o tiff.
    """
    if not pages:
        raise ImagingError("no hay datos que guardar")
    actual = sniff_format(pages[0])

    if target == "pdf":
        if actual == "pdf":
            if len(pages) > 1:
                LOG.warning("se recibieron %d PDF; se guarda solo el primero", len(pages))
            return pages[0]
        if actual == "jpeg":
            return jpeg_to_pdf(pages, dpi)
        return jpeg_to_pdf([convert_with_external_tool(page, actual, "jpg")
                            for page in pages], dpi)

    if len(pages) > 1:
        LOG.warning("se recibieron %d paginas para el formato %s; se guarda la primera",
                    len(pages), target)
    page = pages[0]
    equivalent = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "tiff": "tiff"}
    if equivalent.get(target) == actual:
        return page
    if actual == "unknown":
        raise ImagingError("el escaner devolvio datos en un formato desconocido")
    return convert_with_external_tool(page, actual, target)
