"""Pruebas unitarias: configuracion, modelos, imagen, nombres de fichero."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanqueue import imaging, models, output  # noqa: E402
from scanqueue.config import ConfigError, load_config  # noqa: E402
from scanqueue.escl import build_scan_settings, parse_capabilities, region_for_page  # noqa: E402
from scanqueue.models import Job, JobState, ValidationError  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_airsane import CAPABILITIES, make_jpeg  # noqa: E402


class TestModels(unittest.TestCase):
    def test_normalizacion_de_parametros(self):
        job = Job.create(dpi="300", format="JPG", mode="Color", source="flatbed")
        self.assertEqual(job.dpi, 300)
        self.assertEqual(job.format, "jpg")
        self.assertEqual(job.extension, "jpg")
        self.assertEqual(job.mime, "image/jpeg")
        self.assertEqual(job.source, "Platen")
        self.assertEqual(models.escl_color_mode(job.mode), "RGB24")

    def test_parametros_invalidos(self):
        for params in (
            {"dpi": 5000, "format": "pdf", "mode": "color", "source": "platen"},
            {"dpi": "abc", "format": "pdf", "mode": "color", "source": "platen"},
            {"dpi": 300, "format": "docx", "mode": "color", "source": "platen"},
            {"dpi": 300, "format": "pdf", "mode": "sepia", "source": "platen"},
            {"dpi": 300, "format": "pdf", "mode": "color", "source": "fax"},
        ):
            with self.subTest(params=params), self.assertRaises(ValidationError):
                Job.create(**params)

    def test_nombre_saneado(self):
        self.assertEqual(models.sanitize_name("../../etc/passwd"), "etc_passwd")
        self.assertEqual(models.sanitize_name("   "), "")
        self.assertEqual(models.sanitize_name("factura 2026/03"), "factura_2026_03")

    def test_serializacion_ida_y_vuelta(self):
        job = Job.create(dpi=600, format="pdf", mode="gray", source="platen", name="x")
        job.note("prueba", detalle=1)
        clone = Job.from_dict(job.to_dict())
        self.assertEqual(clone.id, job.id)
        self.assertEqual(clone.state, JobState.QUEUED)
        self.assertEqual(clone.history[-1]["event"], "prueba")

    def test_estados_terminales(self):
        self.assertTrue(JobState.DONE.terminal)
        self.assertTrue(JobState.FAILED.terminal)
        self.assertTrue(JobState.CANCELLED.terminal)
        self.assertFalse(JobState.QUEUED.terminal)
        self.assertFalse(JobState.RETRYING.terminal)


class TestConfig(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._counter = 0

    def _write(self, body: str) -> Path:
        self._counter += 1
        ini = Path(self._tmp.name) / f"scanqueue{self._counter}.ini"
        ini.write_text(body, encoding="utf-8")
        return ini

    def test_valores_por_defecto(self):
        config = load_config(environ={})
        self.assertEqual(config.airsane.base_url, "http://127.0.0.1:8090")
        self.assertEqual(config.scan.max_attempts, 3)
        self.assertEqual(config.scan.default_format, "pdf")
        self.assertTrue(str(config.output.dir).endswith("Nextcloud/Escaneos"))

    def test_ini_y_entorno(self):
        ini = self._write("[scan]\ndefault_dpi = 600\n[output]\ndir = /tmp/salida\n")
        config = load_config(ini, environ={"SCANQUEUE_SCAN_MAX_ATTEMPTS": "5"})
        self.assertEqual(config.scan.default_dpi, 600)
        self.assertEqual(config.scan.max_attempts, 5)
        self.assertEqual(str(config.output.dir), "/tmp/salida")

    def test_errores_de_configuracion(self):
        casos = [
            "[scan]\nmax_attempts = cero\n",
            "[scan]\nbackend = telepatia\n",
            "[airsane]\nbase_url = ftp://x\n",
            "[desconocida]\nx = 1\n",
            "[scan]\nclave_inexistente = 1\n",
            "[scan]\ndefault_format = docx\n",
        ]
        for body in casos:
            with self.subTest(body=body), self.assertRaises(ConfigError):
                load_config(self._write(body), environ={})

    def test_token_oculto_en_describe(self):
        ini = self._write("[service]\nauth_token = secreto\n")
        described = load_config(ini, environ={}).describe()
        self.assertEqual(described["service"]["auth_token"], "***")


class TestImaging(unittest.TestCase):
    def test_deteccion_de_formato(self):
        self.assertEqual(imaging.sniff_format(make_jpeg()), "jpeg")
        self.assertEqual(imaging.sniff_format(b"%PDF-1.4\n"), "pdf")
        self.assertEqual(imaging.sniff_format(imaging.PNG_MAGIC + b"x"), "png")
        self.assertEqual(imaging.sniff_format(b"basura"), "unknown")

    def test_lectura_de_cabecera_jpeg(self):
        self.assertEqual(imaging.jpeg_info(make_jpeg(1240, 1754, 3)), (1240, 1754, 3))
        self.assertEqual(imaging.jpeg_info(make_jpeg(100, 200, 1)), (100, 200, 1))
        with self.assertRaises(imaging.ImagingError):
            imaging.jpeg_info(b"no soy un jpeg")

    def test_jpeg_a_pdf(self):
        pdf = imaging.jpeg_to_pdf([make_jpeg(600, 900)], dpi=300)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"/DCTDecode", pdf)
        self.assertIn(b"/DeviceRGB", pdf)
        # 600 px a 300 ppp = 2 pulgadas = 144 pt
        self.assertIn(b"/MediaBox [0 0 144.00 216.00]", pdf)
        self.assertIn(b"startxref", pdf)
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))

    def test_pdf_multipagina(self):
        pdf = imaging.jpeg_to_pdf([make_jpeg(300, 300), make_jpeg(300, 300)], dpi=300)
        self.assertIn(b"/Count 2", pdf)
        self.assertEqual(pdf.count(b"/DCTDecode"), 2)

    def test_pdf_escala_de_grises(self):
        self.assertIn(b"/DeviceGray",
                      imaging.jpeg_to_pdf([make_jpeg(100, 100, 1)], dpi=300))

    def test_xref_apunta_a_los_objetos(self):
        """La tabla xref debe apuntar al inicio real de cada objeto."""
        pdf = imaging.jpeg_to_pdf([make_jpeg(120, 120)], dpi=300)
        start = pdf.index(b"xref\n")
        lines = pdf[start:].split(b"\n")
        count = int(lines[1].split()[1])
        for index, line in enumerate(lines[3:count + 2], start=1):
            offset = int(line.split()[0])
            self.assertTrue(pdf[offset:].startswith(f"{index} 0 obj".encode()),
                            f"el objeto {index} no esta en el offset {offset}")

    def test_coerce_deja_pasar_el_pdf_del_escaner(self):
        original = b"%PDF-1.4\ncontenido\n%%EOF"
        self.assertEqual(imaging.coerce_format([original], "pdf", 300), original)

    def test_coerce_jpeg_a_jpg_sin_tocar(self):
        data = make_jpeg()
        self.assertEqual(imaging.coerce_format([data], "jpg", 300), data)


class TestOutput(unittest.TestCase):
    def setUp(self):
        self.job = Job.create(dpi=300, format="pdf", mode="color", source="platen",
                              name="factura")

    def test_plantilla(self):
        name = output.render_filename("{name}_{dpi}ppp_{job_id}.{ext}", self.job)
        self.assertEqual(name, f"factura_300ppp_{self.job.id}.pdf")

    def test_la_plantilla_no_escapa_del_directorio(self):
        name = output.render_filename("../../{job_id}.{ext}", self.job)
        self.assertNotIn("/", name)
        self.assertEqual(name, f"{self.job.id}.pdf")

    def test_plantilla_invalida_no_rompe(self):
        name = output.render_filename("{inexistente}.{ext}", self.job)
        self.assertTrue(name.endswith(".pdf"))

    def test_nombres_unicos(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.pdf").write_bytes(b"x")
            self.assertEqual(output.unique_path(directory, "a.pdf").name, "a-1.pdf")
            (directory / "a-1.pdf").write_bytes(b"x")
            self.assertEqual(output.unique_path(directory, "a.pdf").name, "a-2.pdf")


class TestESCLProtocol(unittest.TestCase):
    def test_parseo_de_capacidades(self):
        caps = parse_capabilities(CAPABILITIES.encode())
        self.assertEqual(caps.make_and_model, "Canon G2010 series")
        self.assertIn("image/jpeg", caps.formats)
        self.assertEqual(caps.resolutions, {75, 300, 600})
        self.assertEqual(caps.max_width, 2551)
        self.assertTrue(caps.supports_mode("RGB24"))
        self.assertFalse(caps.supports_format("application/pdf"))

    def test_resolucion_mas_cercana(self):
        caps = parse_capabilities(CAPABILITIES.encode())
        self.assertEqual(caps.closest_resolution(300), 300)
        self.assertEqual(caps.closest_resolution(200), 300)
        self.assertEqual(caps.closest_resolution(1200), 600)

    def test_xml_de_ajustes(self):
        xml = build_scan_settings(dpi=300, mime="image/jpeg", color_mode="RGB24",
                                  source="Platen", region=(2480, 3508)).decode()
        self.assertIn("<scan:XResolution>300</scan:XResolution>", xml)
        self.assertIn("<pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>", xml)
        self.assertIn("<pwg:InputSource>Platen</pwg:InputSource>", xml)
        self.assertIn("<pwg:Width>2480</pwg:Width>", xml)

    def test_region_recortada_a_las_capacidades(self):
        caps = parse_capabilities(CAPABILITIES.encode())
        self.assertEqual(region_for_page("legal", caps), (2550, 3508))
        self.assertIsNone(region_for_page("", caps))


if __name__ == "__main__":
    unittest.main()
