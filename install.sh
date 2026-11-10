#!/usr/bin/env bash
set -euo pipefail
if [[ $(uname -s) != Linux ]]; then
  echo 'Run this installer on the Kali laptop.' >&2
  exit 1
fi
if [[ $EUID == 0 ]]; then
  echo 'Run as your normal desktop user; sudo is used only for system dependencies.' >&2
  exit 1
fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sudo apt-get update
sudo apt-get install -y python3-venv python3-tk bluez network-manager iproute2 iw libnotify-bin tshark
sudo systemctl start bluetooth
python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt"
chmod +x "$project_dir/run.sh"
mkdir -p "$HOME/.local/share/applications"
export AEGIS_INSTALL_DIR="$project_dir"
"$project_dir/.venv/bin/python" - <<'PY'
import os
from pathlib import Path
root = os.environ['AEGIS_INSTALL_DIR']
def quote(s):
    return '"' + s.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%') + '"'
desktop = '[Desktop Entry]\nType=Application\nName=Aegis Field\nComment=Local Bluetooth and Wi-Fi awareness\nExec='+quote(root+'/run.sh')+'\nIcon=network-wireless\nTerminal=false\nCategories=Network;Utility;\n'
(Path.home()/'.local/share/applications/aegis-field.desktop').write_text(desktop)
PY
echo 'Installed. Open Aegis Field from your applications menu, or run ./run.sh.'
echo 'Probe detection starts automatically using your monitor-mode adapter; capture permission is required.'
