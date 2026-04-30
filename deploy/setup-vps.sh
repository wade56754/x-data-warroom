#!/usr/bin/env bash
# setup-vps.sh · X Data Warroom — Ubuntu 22.04 VPS bootstrap
#
# Run on a fresh Ubuntu 22.04 VPS (root or sudo).
# Installs: docker, docker compose v2, git, ufw, caddy.
# Clones the repo, brings up Metabase.
#
# Usage (from your laptop):
#   scp deploy/setup-vps.sh root@<vps-ip>:/root/
#   ssh root@<vps-ip> "bash /root/setup-vps.sh"
#
# Or one-liner:
#   ssh root@<vps-ip> "bash -s" < deploy/setup-vps.sh

set -euo pipefail

REPO="https://github.com/wade56754/x-data-warroom.git"
TARGET_DIR="/opt/warroom"

echo "==> apt update + install"
export DEBIAN_FRONTEND=noninteractive
apt update -y
apt install -y \
    git curl ufw \
    ca-certificates gnupg lsb-release \
    debian-keyring debian-archive-keyring apt-transport-https

echo "==> install docker (official repo)"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt update -y
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker --now

echo "==> install caddy (official repo, optional reverse proxy)"
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
  gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  > /etc/apt/sources.list.d/caddy-stable.list
apt update -y
apt install -y caddy

echo "==> firewall (ufw)"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "ssh"
ufw allow 80/tcp comment "http (caddy)"
ufw allow 443/tcp comment "https (caddy)"
# Note: 3000 (metabase) NOT opened by default; reach via caddy reverse proxy
ufw --force enable

echo "==> clone repo"
mkdir -p "$TARGET_DIR"
if [ ! -d "$TARGET_DIR/.git" ]; then
    git clone "$REPO" "$TARGET_DIR"
else
    cd "$TARGET_DIR" && git pull --rebase
fi
cd "$TARGET_DIR"

echo "==> .env reminder"
if [ ! -f "$TARGET_DIR/.env" ]; then
    echo "[WARN] $TARGET_DIR/.env not present. Copy .env.example and fill before docker compose up:"
    echo "       cp $TARGET_DIR/.env.example $TARGET_DIR/.env"
    echo "       nano $TARGET_DIR/.env  # set METABASE_SUPABASE_*"
fi

echo "==> bring up metabase"
docker compose up -d metabase

echo "==> wait for metabase init (max 5 min)"
for i in {1..30}; do
    if curl -sf http://localhost:3000/api/health >/dev/null 2>&1; then
        echo "[OK] metabase healthy after ${i}*10s"
        break
    fi
    sleep 10
done

curl -sS http://localhost:3000/api/health || echo "[WARN] metabase not yet healthy; check 'docker compose logs metabase'"

echo "==> done. Next steps:"
echo "  1. browser: http://<vps-ip>:3000  (firewall blocks 3000 by default)"
echo "  2. or: configure caddy reverse-proxy (see deploy/Caddyfile.example)"
echo "  3. or: tunnel via SSH: ssh -L 3000:localhost:3000 root@<vps-ip>"
