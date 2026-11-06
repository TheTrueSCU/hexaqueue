#!/bin/bash
set -euo pipefail

echo "==> Bootstrapping Hexaqueue Worker node..."

# Ensure non-interactive apt
export DEBIAN_FRONTEND=noninteractive

# Install curl, jq, python3-venv if not present
apt-get update -y
apt-get install -y --no-install-recommends curl jq python3-venv ca-certificates

# Install uv if missing
if ! command -v uv &>/dev/null; then
  echo "==> Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  cp /root/.local/bin/uv /usr/local/bin/uv
fi

# Configure worker agent environment
mkdir -p /etc/hexaqueue
cat <<EOF > /etc/hexaqueue/worker.env
HEXAQUEUE_CONTROLLER_URL=http://${controller_ip}:${controller_port}
HEXAQUEUE_WORKER_IP=\$(curl -s -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/vnics/ | jq -r '.[0].privateIp')
HEXAQUEUE_WORKER_OCPUS=${worker_ocpus}
EOF

echo "==> Hexaqueue Worker bootstrap complete."
