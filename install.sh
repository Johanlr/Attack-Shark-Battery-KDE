#!/usr/bin/env bash
# Instala o app para o usuario atual. Nada aqui precisa de root, exceto a regra
# udev - e essa e pedida explicitamente, uma vez.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HOME/.local/share/attackshark-tray"
BIN="$HOME/.local/bin"
RULE=/etc/udev/rules.d/70-attackshark-battery.rules

echo "==> installing to $LIB"
mkdir -p "$LIB" "$BIN" "$HOME/.config/systemd/user" \
         "$HOME/.local/share/applications"
rm -rf "$LIB/sharktray"
cp -r "$SRC/sharktray" "$LIB/sharktray"
find "$LIB/sharktray" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

cat > "$BIN/attackshark-tray" <<LAUNCH
#!/usr/bin/env bash
exec python3 -c 'import sys; sys.path.insert(0, "$LIB"); \
import sharktray.app as a; sys.exit(a.main())' "\$@"
LAUNCH
chmod +x "$BIN/attackshark-tray"

install -m 0644 "$SRC/systemd/attackshark-tray.service" \
        "$HOME/.config/systemd/user/attackshark-tray.service"
install -m 0644 "$SRC/systemd/attackshark-tray.desktop" \
        "$HOME/.local/share/applications/attackshark-tray.desktop"
systemctl --user daemon-reload || true

if ! cmp -s "$SRC/udev/70-attackshark-battery.rules" "$RULE" 2>/dev/null; then
  echo "==> the udev rule needs root (it grants read access to the receiver's"
  echo "    vendor interface only, so the app can run without root)"
  # sudo primeiro, mas sem prompt: num terminal sem tty ele falha feio. pkexec
  # cobre a sessao grafica, que e onde este app costuma ser instalado.
  if sudo -n true 2>/dev/null; then
    AS_ROOT="sudo"
  elif command -v pkexec >/dev/null; then
    AS_ROOT="pkexec"
  else
    AS_ROOT="sudo"
  fi
  $AS_ROOT install -m 0644 "$SRC/udev/70-attackshark-battery.rules" "$RULE"
  $AS_ROOT udevadm control --reload
  $AS_ROOT udevadm trigger --action=add --subsystem-match=hidraw
fi

echo
echo "done. start it with:   attackshark-tray"
echo "start at login:        systemctl --user enable --now attackshark-tray"
echo "(or tick 'Start at login' in the app's menu)"
