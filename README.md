# scanqueue

Servicio de cola de escaneo para una **Canon G2010 conectada por USB**, servida en red
por **AirSane** (puerto 8090), pensado para un Linux Mint XFCE modesto
(Core 2 Duo, 3 GB) y empaquetado como **AppImage**.

Acepta trabajos por API HTTP o socket UNIX, los ejecuta **de uno en uno** para no
pelearse por el USB, **reintenta con backoff exponencial**, **espera a que systemd
reinicie airsaned** si se cae, deja el resultado en la carpeta de **Nextcloud** y
registra todo para auditoría.

---

## Por qué está hecho así

| Decisión | Motivo |
|---|---|
| **Python 3 sólo con biblioteca estándar** (sin Flask, sin `requests`, sin Pillow) | El proceso ronda los 15–20 MB de RSS en vez de los ~60 MB de un stack Flask, y el AppImage no arrastra dependencias. En un Core 2 Duo con 3 GB eso se nota. La API tiene la misma forma REST/JSON que tendría con Flask. |
| **Escaneo vía eSCL de AirSane**, no `scanimage` | AirSane ya tiene abierto el dispositivo USB. Lanzar `scanimage` en paralelo es exactamente el conflicto que hay que evitar. Queda `scanimage` como backend de respaldo para cuando airsaned está parado. |
| **Un solo hilo trabajador** | La G2010 no admite escaneos concurrentes; AirSane respondería `409`. La cola serializa por diseño, no por casualidad. |
| **Cola persistida en SQLite** | Si el servicio se reinicia a mitad de faena, los trabajos pendientes se recuperan en vez de perderse. |
| **PDF generado embebiendo el JPEG (DCTDecode)** | No hace falta Pillow ni recomprimir: se envuelve el JPEG del escáner tal cual. Rápido y sin dependencias. |
| **Spool de reserva** | Si la carpeta de Nextcloud no está disponible (no montada, sin permisos), el escaneo **no se pierde**: va a `~/.local/share/scanqueue/spool/`. Repetir un escaneo obliga a volver a poner el papel; guardarlo en otro sitio no. |

---

## Instalación

### 1. Construir el AppImage

```bash
git clone https://github.com/pickatroll12-arch/printer.git
cd printer
./packaging/build-appimage.sh              # embebe su propio CPython (~35 MB)
./packaging/build-appimage.sh --system-python   # ligero (~100 KB), usa el python3 del sistema
```

El resultado queda en `dist/scanqueue-x86_64.AppImage`.

> Mint 21+ no trae `libfuse2`. Si el AppImage no arranca:
> `sudo apt install libfuse2`, o ejecútalo con `--appimage-extract-and-run`.

### 2. Instalar

```bash
./packaging/install.sh          # binario + configuración + unidad de systemd
```

O a mano:

```bash
sudo install -m 0755 dist/scanqueue-x86_64.AppImage /usr/local/bin/scanqueue
mkdir -p ~/.config/scanqueue
cp packaging/scanqueue.ini.example ~/.config/scanqueue/scanqueue.ini
mkdir -p ~/.config/systemd/user
cp packaging/scanqueue.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now scanqueue
sudo loginctl enable-linger "$USER"   # que arranque sin iniciar sesión gráfica
```

### 3. Comprobar

```bash
scanqueue health
scanqueue capabilities      # ppp y formatos que anuncia la G2010
scanqueue scan --dpi 300 --format pdf --wait
```

---

## Uso

### CLI

```bash
scanqueue scan --dpi 300 --format pdf --mode color --name factura --wait
scanqueue list
scanqueue status <id>
scanqueue cancel <id>
scanqueue health
scanqueue config          # configuración efectiva (el token sale enmascarado)
```

Cualquier orden acepta `--json` para scripts. El cliente usa el socket UNIX si
existe y si no la API HTTP; se puede forzar con `--transport unix|http`.

### API HTTP

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/health` | Estado del servicio y de airsaned (`503` si airsaned está caído) |
| `GET` | `/info` | Versión y configuración efectiva |
| `GET` | `/capabilities` | Resoluciones, formatos y modos del escáner |
| `POST` | `/jobs` | Encola un trabajo → `202` con el trabajo creado |
| `GET` | `/jobs` | Lista trabajos (`?state=&limit=&offset=`) |
| `GET` | `/jobs/<id>` | Estado de un trabajo |
| `DELETE` | `/jobs/<id>` | Cancela un trabajo |
| `GET` | `/jobs/<id>/file` | Descarga el resultado |

```bash
curl -s -X POST http://127.0.0.1:8099/jobs \
     -H 'Content-Type: application/json' \
     -d '{"dpi": 300, "format": "pdf", "mode": "color", "name": "recibo"}'

curl -s http://127.0.0.1:8099/jobs/ab12cd34ef56 | python3 -m json.tool
```

También acepta `application/x-www-form-urlencoded`, cómodo desde un botón del panel:

```bash
curl -s -X POST http://127.0.0.1:8099/jobs -d 'dpi=600&format=jpeg'
```

Si defines `auth_token`, añade `Authorization: Bearer <token>` (o `?token=`).
**Es obligatorio si cambias `host` a `0.0.0.0`.**

### Socket UNIX

Una línea JSON por petición, una línea JSON por respuesta:

```bash
printf '{"command":"scan","dpi":300,"format":"pdf"}\n' | nc -U ~/.local/share/scanqueue/scanqueue.sock
printf '{"command":"health"}\n' | nc -U ~/.local/share/scanqueue/scanqueue.sock
```

Comandos: `scan`, `status`, `list`, `cancel`, `health`, `capabilities`, `info`,
`stats`, `ping`.

### Parámetros de un trabajo

| Campo | Valores | Por defecto |
|---|---|---|
| `dpi` | 50–1200 (se ajusta al más cercano que soporte el escáner) | `300` |
| `format` | `pdf`, `jpeg`, `png`, `tiff` | `pdf` |
| `mode` | `color`, `gray`, `lineart` | `color` |
| `source` | `platen` (cristal), `adf` | `platen` |
| `page` | `max`, `a4`, `letter`, `legal`, `a5`, `a6` | `max` (el `.ini` de ejemplo pone `a4`) |
| `name` | Nombre base del fichero (se sanea) | — |
| `max_attempts` | Tope de intentos de este trabajo | `3` |

---

## Ciclo de vida de un trabajo

```
queued ──> waiting_backend ──> running ──> done
   │             (airsaned caído)   │
   │                                ├──> retrying ──> running ...
   │                                └──> failed
   └──> cancelled
```

Antes de **cada intento** se comprueba airsaned. Si no responde, el trabajo pasa a
`waiting_backend` y se espera activamente (`health_poll`, hasta `health_wait`
segundos) a que systemd lo reinicie — **sin gastar intentos**. Los intentos sólo
se consumen en fallos de escaneo reales.

Los reintentos usan backoff exponencial `backoff_base × backoff_factor^(n-1)`,
con tope `backoff_max` y ±20 % de *jitter*: 4 s, 8 s, 16 s… Un rechazo de
parámetros (HTTP 400/415) **no se reintenta**: repetirlo daría el mismo error.

---

## Registro y auditoría

- `~/.local/share/scanqueue/scanqueue.log` — log rotativo (5 MB × 5).
- `~/.local/share/scanqueue/audit.jsonl` — un evento JSON por línea:
  `job.submitted`, `job.attempt`, `job.attempt_failed`, `job.completed`,
  `job.failed`, `job.cancelled`, `backend.unhealthy`, `backend.recovered`,
  `backend.timeout`, `service.started`, `service.stopped`.

```bash
# Trabajos fallidos de hoy
grep '"event": "job.failed"' ~/.local/share/scanqueue/audit.jsonl | tail

# Tiempo medio de escaneo
python3 -c "import json,sys; v=[json.loads(l)['seconds'] for l in open('$HOME/.local/share/scanqueue/audit.jsonl') if '\"job.completed\"' in l]; print(sum(v)/len(v))"
```

El historial en base de datos se purga según `history_days`. **Nunca se borra
ningún fichero escaneado.**

---

## Problemas frecuentes

| Síntoma | Qué mirar |
|---|---|
| `no se encontro ningun escaner eSCL` | ¿`curl http://127.0.0.1:8090/` responde? ¿La G2010 aparece en la página de AirSane? Fija `airsane.scanner` con el nombre exacto si hay varios. |
| Los trabajos se quedan en `waiting_backend` | `systemctl status airsaned`. `scanqueue health` muestra también el estado de la unidad. |
| El PDF sale con el tamaño de página raro | El PDF se dimensiona con los ppp reales. Si pides 200 ppp y el escáner sólo hace 300, el tamaño se ajusta a los 300 usados. |
| `png`/`tiff` fallan | La G2010 vía AirSane entrega JPEG. Para esos formatos hace falta `imagemagick` (`sudo apt install imagemagick`); PDF y JPEG no necesitan nada. |
| Todo va a `spool/` en vez de a Nextcloud | La carpeta no existe o no se puede escribir. `scanqueue health` trae `output_writable`. |
| El AppImage no arranca | `sudo apt install libfuse2`, o `./scanqueue-x86_64.AppImage --appimage-extract-and-run health`. |
| El servicio arranca y systemd lo mata a los 90 s | Falta `NotifyAccess=all` en la unidad. El runtime del AppImage se bifurca, así que el `READY=1` lo manda un proceso hijo y con `NotifyAccess=main` systemd lo descarta. La unidad incluida ya lo trae; si tienes una propia, añádelo. Por lo mismo, no uses `KillMode=mixed`: la señal de parada se quedaría en el envoltorio. |

---

## Desarrollo

```bash
python3 -m unittest discover -s tests -v      # 56 pruebas
python3 -m scanqueue serve -c ./mi.ini        # sin instalar
```

Las pruebas levantan un **AirSane simulado** (`tests/fake_airsane.py`) con
interruptores para provocar caídas, errores 500 y rechazos de parámetros, y
verifican el flujo completo: PDF real en disco, serialización de la cola,
reintentos, espera del backend, persistencia entre reinicios, API HTTP con y sin
token, y el socket UNIX.

Requisitos: Python ≥ 3.9. Sin dependencias de terceros.

Estructura:

```
scanqueue/
  cli.py          demonio y cliente
  service.py      fachada que une todo
  worker.py       cola, reintentos, backoff, control de salud
  escl.py         cliente eSCL de AirSane
  backends.py     eSCL / scanimage
  health.py       vigilancia de airsaned y espera activa
  imaging.py      JPEG -> PDF sin dependencias
  output.py       escritura atómica en Nextcloud + spool de reserva
  store.py        persistencia SQLite
  http_api.py     API HTTP JSON
  unix_socket.py  protocolo JSON por líneas
```
