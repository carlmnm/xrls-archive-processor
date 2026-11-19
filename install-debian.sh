#!/usr/bin/env bash
# Instala as dependências no Debian/Ubuntu e cria o comando "xrls".
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "› Instalando FFmpeg, Python e certificados (pede a senha do sudo)…"
sudo apt update
sudo apt install -y ffmpeg python3 python3-certifi xdg-utils

chmod +x "$DIR/processor6.py"
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/processor6.py" "$HOME/.local/bin/xrls"

echo
echo "✓ Pronto! Abra um novo terminal e rode:  xrls"
echo "  (ou, sem instalar o atalho:  python3 $DIR/processor6.py)"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "! ~/.local/bin não está no PATH; adicione ao seu ~/.bashrc:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
