#!/bin/bash
set -euo pipefail

echo "==> Bootstrapping Hexaqueue Worker node..."

# Ensure non-interactive apt
export DEBIAN_FRONTEND=noninteractive

# Install curl, jq, git, python3-venv if not present
apt-get update -y
apt-get install -y --no-install-recommends curl jq git python3-venv ca-certificates

# Install uv if missing
if ! command -v uv &>/dev/null; then
  echo "==> Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  cp /root/.local/bin/uv /usr/local/bin/uv
fi

# Clone hexaqueue repository to /opt/hexaqueue
if [ ! -d "/opt/hexaqueue" ]; then
  echo "==> Cloning hexaqueue repository..."
  git clone https://github.com/TheTrueSCU/hexaqueue.git /opt/hexaqueue
else
  echo "==> Updating hexaqueue repository..."
  cd /opt/hexaqueue && git fetch origin main && git reset --hard origin/main
fi

# Pre-sync worker dependencies
echo "==> Syncing worker environment via uv..."
cd /opt/hexaqueue
/usr/local/bin/uv sync --all-packages

# Configure worker agent environment
mkdir -p /etc/hexaqueue
PRIVATE_IP=$(curl -s -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/vnics/ | jq -r '.[0].privateIp // empty')
cat <<EOF > /etc/hexaqueue/worker.env
HEXAQUEUE_CONTROLLER_URL=http://${controller_ip}:${controller_port}
HEXAQUEUE_WORKER_IP=$PRIVATE_IP
HEXAQUEUE_WORKER_OCPUS=${worker_ocpus}
HEXAQUEUE_AGENT_IDLE_TIMEOUT=900.0
EOF

# Create and enable systemd service for worker agent
cat <<EOF > /etc/systemd/system/hexaqueue-worker.service
[Unit]
Description=Hexaqueue Burst Worker Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/hexaqueue
EnvironmentFile=/etc/hexaqueue/worker.env
ExecStart=/usr/local/bin/uv run python3 -m hexaqueue_worker.adapters.agent
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now hexaqueue-worker.service

echo "==> Hexaqueue Worker bootstrap complete. Service active."
