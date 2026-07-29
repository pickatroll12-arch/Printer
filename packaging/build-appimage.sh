#!/usr/bin/env bash
# Construye scanqueue-x86_64.AppImage.
#
# Dos modos:
#   completo  (por defecto) embebe un CPython de python-appimage -> no depende
#             del Python del sistema. Necesita red la primera vez.
#   --system-python  AppImage ligero (~100 KB) que usa el python3 del sistema.
#             Util si no hay red o si quieres el minimo tamaño posible.
#
# Uso:
#   ./packaging/build-appimage.sh                # completo
#   ./packaging/build-appimage.sh --system-python
#   PYTHON_VERSION=3.11.9 ./packaging/build-appimage.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$REPO_ROOT/build}"
DIST_DIR="${DIST_DIR:-$REPO_ROOT/dist}"
CACHE_DIR="${CACHE_DIR:-$BUILD_DIR/cache}"
APPDIR="$BUILD_DIR/scanqueue.AppDir"
ARCH="${ARCH:-x86_64}"

PYTHON_VERSION="${PYTHON_VERSION:-3.11.9}"
PYTHON_TAG="${PYTHON_TAG:-cp311-cp311}"
PYTHON_APPIMAGE_RELEASE="${PYTHON_APPIMAGE_RELEASE:-python${PYTHON_VERSION}}"
PYTHON_APPIMAGE_URL="${PYTHON_APPIMAGE_URL:-https://github.com/niess/python-appimage/releases/download/${PYTHON_APPIMAGE_RELEASE}/python${PYTHON_VERSION}-${PYTHON_TAG}-manylinux2014_${ARCH}.AppImage}"
APPIMAGETOOL_URL="${APPIMAGETOOL_URL:-https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage}"

MODE="full"
[[ "${1:-}" == "--system-python" ]] && MODE="system"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()   { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

fetch() {  # fetch <url> <destino>
    local url="$1" dest="$2"
    [[ -f "$dest" ]] && { info "en cache: $(basename "$dest")"; return 0; }
    info "descargando $(basename "$dest")"
    mkdir -p "$(dirname "$dest")"
    if command -v curl >/dev/null; then
        curl -fL --retry 3 --connect-timeout 20 -o "$dest.part" "$url" \
            || die "no se pudo descargar $url"
    elif command -v wget >/dev/null; then
        wget -q --tries=3 -O "$dest.part" "$url" || die "no se pudo descargar $url"
    else
        die "hace falta curl o wget para descargar $url"
    fi
    mv "$dest.part" "$dest"
}

run_appimage() {  # ejecuta un AppImage aunque no haya FUSE
    local image="$1"; shift
    chmod +x "$image"
    if "$image" --appimage-extract-and-run "$@" 2>/dev/null; then
        return 0
    fi
    "$image" "$@"
}

# ------------------------------------------------------------------ preparacion

info "comprobando el codigo antes de empaquetar"
( cd "$REPO_ROOT" && python3 -m compileall -q scanqueue >/dev/null ) \
    || die "el paquete scanqueue no compila"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/scanqueue-app" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps" "$DIST_DIR"

# ------------------------------------------------------- interprete (modo full)

if [[ "$MODE" == "full" ]]; then
    BASE_IMAGE="$CACHE_DIR/python-base.AppImage"
    fetch "$PYTHON_APPIMAGE_URL" "$BASE_IMAGE"
    info "extrayendo el interprete embebido"
    rm -rf "$BUILD_DIR/python-extract"
    mkdir -p "$BUILD_DIR/python-extract"
    ( cd "$BUILD_DIR/python-extract" && run_appimage "$BASE_IMAGE" --appimage-extract >/dev/null )
    SQUASH="$BUILD_DIR/python-extract/squashfs-root"
    [[ -d "$SQUASH/opt" ]] || die "el AppImage base no tiene el interprete esperado"
    cp -a "$SQUASH/opt" "$APPDIR/"
    # Nos quedamos solo con lo necesario: sin tests ni pip (no hay dependencias).
    find "$APPDIR/opt" -type d \( -name test -o -name tests -o -name idlelib \
        -o -name tkinter -o -name turtledemo -o -name __pycache__ \) \
        -prune -exec rm -rf {} + 2>/dev/null || true
    find "$APPDIR/opt" -type d -name 'pip*' -prune -exec rm -rf {} + 2>/dev/null || true
else
    info "modo --system-python: el AppImage usara el python3 del sistema"
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
        || warn "este equipo tiene un Python anterior a 3.9; scanqueue necesita >= 3.9"
fi

# ------------------------------------------------------------------ aplicacion

info "copiando scanqueue"
cp -a "$REPO_ROOT/scanqueue" "$APPDIR/usr/lib/scanqueue-app/"
find "$APPDIR/usr/lib/scanqueue-app" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

install -m 0755 "$REPO_ROOT/packaging/AppRun" "$APPDIR/AppRun"
install -m 0644 "$REPO_ROOT/packaging/scanqueue.desktop" "$APPDIR/scanqueue.desktop"
install -m 0644 "$REPO_ROOT/packaging/scanqueue.desktop" \
    "$APPDIR/usr/share/applications/scanqueue.desktop"
install -m 0644 "$REPO_ROOT/packaging/scanqueue.svg" "$APPDIR/scanqueue.svg"
install -m 0644 "$REPO_ROOT/packaging/scanqueue.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/scanqueue.svg"
install -m 0644 "$REPO_ROOT/packaging/scanqueue.ini.example" \
    "$APPDIR/usr/lib/scanqueue-app/scanqueue.ini.example"
install -m 0644 "$REPO_ROOT/packaging/scanqueue.service" \
    "$APPDIR/usr/lib/scanqueue-app/scanqueue.service"

info "prueba de humo del AppDir"
APPDIR="$APPDIR" "$APPDIR/AppRun" --version >/dev/null || die "el AppDir no arranca"

# ------------------------------------------------------------------- empaquetar

TOOL="$CACHE_DIR/appimagetool.AppImage"
fetch "$APPIMAGETOOL_URL" "$TOOL"
OUTPUT="$DIST_DIR/scanqueue-${ARCH}.AppImage"
info "generando $OUTPUT"
ARCH="$ARCH" run_appimage "$TOOL" "$APPDIR" "$OUTPUT" >/dev/null \
    || die "appimagetool fallo (¿falta FUSE? prueba: sudo apt install libfuse2)"
chmod +x "$OUTPUT"

info "listo: $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
echo
echo "  Prueba rapida:  $OUTPUT health"
echo "  Instalar:       sudo install -m 0755 $OUTPUT /usr/local/bin/scanqueue"
