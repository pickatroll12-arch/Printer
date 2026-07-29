#!/usr/bin/env bash
# Instala scanqueue: binario, configuracion y servicio de usuario de systemd.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPIMAGE="${APPIMAGE:-$REPO_ROOT/dist/scanqueue-x86_64.AppImage}"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/scanqueue}"
UNIT_DIR="${UNIT_DIR:-$HOME/.config/systemd/user}"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ -f "$APPIMAGE" ]] || die "no existe $APPIMAGE (ejecuta antes packaging/build-appimage.sh)"

info "instalando el binario en $BIN_DIR/scanqueue"
if [[ -w "$BIN_DIR" ]]; then
    install -m 0755 "$APPIMAGE" "$BIN_DIR/scanqueue"
else
    sudo install -m 0755 "$APPIMAGE" "$BIN_DIR/scanqueue"
fi

mkdir -p "$CONFIG_DIR"
if [[ -f "$CONFIG_DIR/scanqueue.ini" ]]; then
    info "se conserva la configuracion existente ($CONFIG_DIR/scanqueue.ini)"
    install -m 0644 "$REPO_ROOT/packaging/scanqueue.ini.example" \
        "$CONFIG_DIR/scanqueue.ini.example"
else
    info "creando $CONFIG_DIR/scanqueue.ini"
    install -m 0644 "$REPO_ROOT/packaging/scanqueue.ini.example" \
        "$CONFIG_DIR/scanqueue.ini"
fi

OUTPUT_DIR="$(sed -n 's/^dir *= *//p' "$CONFIG_DIR/scanqueue.ini" | head -1)"
OUTPUT_DIR="${OUTPUT_DIR/#\~/$HOME}"
if [[ -n "$OUTPUT_DIR" ]]; then
    info "preparando la carpeta de salida $OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR" || info "no se pudo crear (¿Nextcloud aun sin montar?)"
fi

info "instalando el servicio de usuario"
mkdir -p "$UNIT_DIR"
install -m 0644 "$REPO_ROOT/packaging/scanqueue.service" "$UNIT_DIR/scanqueue.service"
systemctl --user daemon-reload
systemctl --user enable --now scanqueue.service

echo
info "instalado. Comprobaciones:"
echo "  systemctl --user status scanqueue"
echo "  scanqueue health"
echo "  scanqueue scan --dpi 300 --format pdf --wait"
echo
echo "Para que arranque sin iniciar sesion grafica:"
echo "  sudo loginctl enable-linger $USER"
