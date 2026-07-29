"""Pruebas de integracion contra un AirSane simulado: cola, reintentos y APIs."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_airsane import FakeAirSane  # noqa: E402

from scanqueue.config import load_config  # noqa: E402
from scanqueue.escl import http_request  # noqa: E402
from scanqueue.models import JobState  # noqa: E402
from scanqueue.service import ScanService  # noqa: E402
from scanqueue.unix_socket import handle_command, send_command  # noqa: E402

TIMEOUT = 30.0


def wait_for(predicate, timeout: float = TIMEOUT, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class ServiceHarness(unittest.TestCase):
    """Base con un servicio real apuntando a un AirSane simulado."""

    extra_config = ""

    def setUp(self):
        self.airsane = FakeAirSane().__enter__()
        self.addCleanup(self.airsane.__exit__, None, None, None)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.output_dir = root / "Nextcloud" / "Escaneos"

        ini = root / "scanqueue.ini"
        ini.write_text(
            f"[service]\nport = 0\nstate_dir = {root / 'state'}\n"
            f"[airsane]\nbase_url = {self.airsane.url}\n"
            f"health_timeout = 3\nhealth_wait = 20\nhealth_poll = 0.1\n"
            f"systemd_unit =\n"
            f"[scan]\njob_timeout = 15\nbackoff_base = 0.05\nbackoff_max = 0.2\n"
            f"[output]\ndir = {self.output_dir}\n"
            f"[logging]\nconsole = false\nfile = {root / 'sq.log'}\n"
            f"audit_file = {root / 'audit.jsonl'}\n" + self.extra_config,
            encoding="utf-8")

        self.config = load_config(ini, environ={})
        self.service = ScanService(self.config)
        self.service.start()
        self.addCleanup(self.service.stop)

    def submit_and_wait(self, params: dict | None = None,
                        expect: JobState = JobState.DONE):
        job = self.service.submit(params or {"dpi": 300, "format": "pdf"})
        self.assertTrue(
            wait_for(lambda: self.service.get(job.id).state.terminal),
            f"el trabajo no termino; ultimo estado: {self.service.get(job.id).state}")
        final = self.service.get(job.id)
        self.assertEqual(final.state, expect, final.error)
        return final

    def audit_events(self) -> list[dict]:
        path = self.config.logging.audit_file
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestFlujoCompleto(ServiceHarness):
    def test_escaneo_correcto_guarda_pdf_en_nextcloud(self):
        job = self.submit_and_wait({"dpi": 300, "format": "pdf", "name": "recibo"})
        self.assertIsNotNone(job.output_path)
        path = Path(job.output_path)
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.output_dir)
        self.assertTrue(path.read_bytes().startswith(b"%PDF"))
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.output_bytes, path.stat().st_size)
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o644")

    def test_formato_jpeg_se_guarda_tal_cual(self):
        job = self.submit_and_wait({"dpi": 300, "format": "jpeg"})
        data = Path(job.output_path).read_bytes()
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))
        self.assertTrue(job.output_path.endswith(".jpg"))

    def test_los_parametros_llegan_al_escaner(self):
        self.submit_and_wait({"dpi": 600, "format": "pdf", "mode": "gray",
                              "page": "a4"})
        settings = self.airsane.last_settings.decode()
        self.assertIn("<scan:XResolution>600</scan:XResolution>", settings)
        self.assertIn("<scan:ColorMode>Grayscale8</scan:ColorMode>", settings)
        self.assertIn("<pwg:Width>2480</pwg:Width>", settings)

    def test_dpi_no_soportado_cae_al_mas_cercano(self):
        self.submit_and_wait({"dpi": 200, "format": "pdf"})
        self.assertIn("<scan:XResolution>300</scan:XResolution>",
                      self.airsane.last_settings.decode())

    def test_un_trabajo_a_la_vez(self):
        """Con dos trabajos encolados nunca hay dos escaneos simultaneos."""
        self.airsane.pages_per_job = 1
        jobs = [self.service.submit({"dpi": 300, "format": "jpeg"}) for _ in range(4)]
        self.assertTrue(wait_for(
            lambda: all(self.service.get(j.id).state.terminal for j in jobs)))
        for job in jobs:
            self.assertEqual(self.service.get(job.id).state, JobState.DONE)

        # Cada POST /ScanJobs debe cerrarse (404 de NextDocument) antes del siguiente.
        secuencia = [path for method, path in self.airsane.requests
                     if method == "POST" or path.endswith("NextDocument")]
        abiertos = 0
        for entrada in secuencia:
            if entrada.endswith("ScanJobs"):
                abiertos += 1
                self.assertLessEqual(abiertos, 1, "hubo dos escaneos solapados")
            else:
                abiertos = 0

    def test_auditoria_registra_el_ciclo_completo(self):
        job = self.submit_and_wait()
        eventos = [e["event"] for e in self.audit_events() if e.get("job_id") == job.id]
        self.assertIn("job.submitted", eventos)
        self.assertIn("job.attempt", eventos)
        self.assertIn("job.completed", eventos)
        self.assertTrue(self.config.logging.file.exists())
        self.assertIn("completado", self.config.logging.file.read_text())


class TestReintentos(ServiceHarness):
    def test_reintenta_y_acaba_bien(self):
        self.airsane.fail_next_document = 2
        job = self.submit_and_wait({"dpi": 300, "format": "pdf"})
        self.assertEqual(job.attempts, 3)
        self.assertTrue(Path(job.output_path).is_file())

    def test_se_rinde_tras_tres_intentos(self):
        self.airsane.fail_next_document = 99
        job = self.submit_and_wait(expect=JobState.FAILED)
        self.assertEqual(job.attempts, 3)
        self.assertIsNotNone(job.error)
        eventos = [e for e in self.audit_events() if e["event"] == "job.attempt_failed"]
        self.assertEqual(len(eventos), 3)
        self.assertFalse(eventos[-1]["will_retry"])

    def test_backoff_exponencial_creciente(self):
        delays = [self.service.worker._backoff_delay(n) for n in (1, 2, 3)]
        # base 0.05, factor 2 -> 0.05, 0.10, 0.20 (con jitter +-20%)
        self.assertLess(delays[0], delays[2])
        self.assertLessEqual(max(delays), self.config.scan.backoff_max * 1.2)

    def test_ajustes_rechazados_no_se_reintentan(self):
        """Un 400 del escaner es un error de parametros: reintentar no ayuda."""
        self.airsane.scanjobs_status = 400
        job = self.submit_and_wait(expect=JobState.FAILED)
        self.assertEqual(job.attempts, 1)

    def test_max_attempts_por_trabajo(self):
        self.airsane.fail_next_document = 99
        job = self.submit_and_wait({"dpi": 300, "format": "pdf", "max_attempts": 1},
                                   expect=JobState.FAILED)
        self.assertEqual(job.attempts, 1)


class TestSaludDelBackend(ServiceHarness):
    def test_espera_a_que_airsaned_vuelva(self):
        self.airsane.down = True

        def revivir():
            time.sleep(1.0)
            self.airsane.down = False

        threading.Thread(target=revivir, daemon=True).start()
        job = self.submit_and_wait({"dpi": 300, "format": "pdf"})
        self.assertEqual(job.attempts, 1, "no debio gastar intentos esperando")
        eventos = [e["event"] for e in self.audit_events()]
        self.assertIn("backend.unhealthy", eventos)
        self.assertIn("backend.recovered", eventos)

    def test_si_no_vuelve_el_trabajo_falla_con_motivo(self):
        self.airsane.down = True
        self.service.config.airsane.__dict__  # config congelada; ajustamos el monitor
        self.service.health.cfg = type(self.service.health.cfg)(
            **{**self.service.health.cfg.__dict__, "health_wait": 0.3})
        job = self.submit_and_wait(expect=JobState.FAILED)
        self.assertIn("airsaned", (job.error or "").lower())

    def test_health_view_refleja_la_caida(self):
        self.assertTrue(self.service.health_view()["airsane"]["healthy"])
        self.airsane.down = True
        report = self.service.health_view()
        self.assertFalse(report["airsane"]["healthy"])
        self.assertIn("503", report["airsane"]["detail"])


class TestPersistenciaYCancelacion(ServiceHarness):
    def test_cancelar_un_trabajo_en_cola(self):
        self.airsane.fail_next_document = 1  # entretiene al trabajador
        primero = self.service.submit({"dpi": 300, "format": "pdf"})
        segundo = self.service.submit({"dpi": 300, "format": "pdf"})
        cancelado = self.service.cancel(segundo.id)
        self.assertEqual(cancelado.state, JobState.CANCELLED)
        self.assertTrue(wait_for(lambda: self.service.get(primero.id).state.terminal))
        self.assertIsNone(self.service.get(segundo.id).output_path)

    def test_la_cola_sobrevive_al_reinicio(self):
        self.airsane.down = True
        job = self.service.submit({"dpi": 300, "format": "pdf"})
        self.assertTrue(wait_for(
            lambda: self.service.get(job.id).state is JobState.WAITING_BACKEND, 10))
        self.service.stop()

        self.airsane.down = False
        revivido = ScanService(self.config)
        self.addCleanup(revivido.stop)
        revivido.start()
        self.assertTrue(wait_for(lambda: revivido.get(job.id).state.terminal))
        self.assertEqual(revivido.get(job.id).state, JobState.DONE)

    def test_cola_llena(self):
        from scanqueue.worker import QueueFull

        self.service.config.service.__dict__  # dataclass congelado
        self.service.worker.config = type(self.service.config)(
            **{**self.service.config.__dict__,
               "service": type(self.service.config.service)(
                   **{**self.service.config.service.__dict__, "max_queue": 1})})
        self.airsane.down = True  # el trabajador se queda esperando
        self.service.submit({"dpi": 300, "format": "pdf"})
        self.assertTrue(wait_for(lambda: self.service.worker.stats()["queued"] >= 1
                                 or self.service.worker.stats()["running"], 5))
        with self.assertRaises(QueueFull):
            for _ in range(5):
                self.service.submit({"dpi": 300, "format": "pdf"})

    def test_salida_de_reserva_si_nextcloud_no_esta(self):
        """Si la carpeta de Nextcloud no se puede escribir, no se pierde el escaneo."""
        # Un fichero donde deberia estar el directorio: mkdir fallara siempre,
        # tambien como root (chmod no serviria en ese caso).
        self.output_dir.rmdir()  # el servicio ya la habia creado vacia
        self.output_dir.write_text("esto no es una carpeta")
        job = self.submit_and_wait({"dpi": 300, "format": "jpeg"})
        self.assertTrue(Path(job.output_path).is_file())
        self.assertIn("spool", job.output_path)


class TestAPIHTTP(ServiceHarness):
    def setUp(self):
        super().setUp()
        from scanqueue.http_api import serve_in_thread

        self.server, _ = serve_in_thread(self.service)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def get(self, path: str, method: str = "GET", payload: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        response = http_request(self.base + path, method=method, data=body,
                               headers={"Content-Type": "application/json"}, timeout=10)
        data = json.loads(response.body) if response.body and \
            response.headers.get("content-type", "").startswith("application/json") else None
        return response, data

    def test_ciclo_por_http(self):
        response, data = self.get("/jobs", "POST", {"dpi": 300, "format": "pdf"})
        self.assertEqual(response.status, 202)
        job_id = data["id"]

        self.assertTrue(wait_for(lambda: self.get(f"/jobs/{job_id}")[1]["state"] == "done"))
        _, job = self.get(f"/jobs/{job_id}")
        self.assertEqual(job["state"], "done")

        response, _ = self.get(f"/jobs/{job_id}/file")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.header("content-type"), "application/pdf")
        self.assertTrue(response.body.startswith(b"%PDF"))
        self.assertIn("attachment", response.header("content-disposition"))

    def test_health_y_listado(self):
        response, data = self.get("/health")
        self.assertEqual(response.status, 200)
        self.assertTrue(data["airsane"]["healthy"])

        self.airsane.down = True
        response, _ = self.get("/health")
        self.assertEqual(response.status, 503)
        self.airsane.down = False

        response, data = self.get("/jobs")
        self.assertEqual(response.status, 200)
        self.assertIn("queue", data)

    def test_errores_de_la_api(self):
        response, data = self.get("/jobs", "POST", {"dpi": 99999})
        self.assertEqual(response.status, 400)
        self.assertIn("dpi", data["error"])

        response, _ = self.get("/jobs/noexiste")
        self.assertEqual(response.status, 404)

        response, _ = self.get("/ruta/inventada")
        self.assertEqual(response.status, 404)

        response, _ = self.get("/health", "DELETE")
        self.assertIn(response.status, (404, 405))

    def test_formulario_urlencoded(self):
        body = urllib.parse.urlencode({"dpi": "300", "format": "jpeg"}).encode()
        response = http_request(
            self.base + "/jobs", method="POST", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
        self.assertEqual(response.status, 202)
        self.assertEqual(json.loads(response.body)["format"], "jpeg")

    def test_capacidades(self):
        _, data = self.get("/capabilities")
        self.assertTrue(data["available"])
        self.assertEqual(data["make_and_model"], "Canon G2010 series")


class TestAPIHTTPConToken(ServiceHarness):
    extra_config = "\n"

    def setUp(self):
        super().setUp()
        from scanqueue.http_api import serve_in_thread

        # Inyectamos el token en la configuracion ya cargada.
        service_cfg = type(self.service.config.service)(
            **{**self.service.config.service.__dict__, "auth_token": "s3cr3t"})
        self.service.config = type(self.service.config)(
            **{**self.service.config.__dict__, "service": service_cfg})
        self.server, _ = serve_in_thread(self.service)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_sin_token_401(self):
        self.assertEqual(http_request(self.base + "/health", timeout=5).status, 401)

    def test_con_token_ok(self):
        response = http_request(self.base + "/health",
                                headers={"Authorization": "Bearer s3cr3t"}, timeout=5)
        self.assertEqual(response.status, 200)

    def test_token_erroneo_401(self):
        response = http_request(self.base + "/health",
                                headers={"Authorization": "Bearer otro"}, timeout=5)
        self.assertEqual(response.status, 401)


class TestSocketUnix(ServiceHarness):
    def setUp(self):
        super().setUp()
        from scanqueue.unix_socket import serve_in_thread

        self.socket_path = Path(self.tmp.name) / "sq.sock"
        self.server, _ = serve_in_thread(self.service, self.socket_path)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_ping_y_escaneo(self):
        self.assertTrue(send_command(self.socket_path, {"command": "ping"})["pong"])

        response = send_command(self.socket_path,
                                {"command": "scan", "dpi": 300, "format": "pdf"})
        self.assertTrue(response["ok"])
        job_id = response["job"]["id"]

        self.assertTrue(wait_for(
            lambda: send_command(self.socket_path,
                                 {"command": "status", "job_id": job_id}
                                 )["job"]["state"] == "done"))

    def test_errores_del_socket(self):
        response = send_command(self.socket_path, {"command": "scan", "dpi": "x"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["kind"], "validation")

        response = send_command(self.socket_path, {"command": "status", "job_id": "nope"})
        self.assertEqual(response["kind"], "not_found")

        response = send_command(self.socket_path, {"command": "bailar"})
        self.assertFalse(response["ok"])

    def test_comandos_de_consulta(self):
        for command in ("health", "capabilities", "info", "stats", "list"):
            with self.subTest(command=command):
                self.assertTrue(
                    send_command(self.socket_path, {"command": command})["ok"])

    def test_permisos_del_socket(self):
        self.assertEqual(oct(self.socket_path.stat().st_mode & 0o777), "0o660")

    def test_handle_command_directo(self):
        response = handle_command(self.service, {"command": "stats"})
        self.assertIn("queued", response["queue"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
