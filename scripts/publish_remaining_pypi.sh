#!/usr/bin/env bash
# ==============================================================================
# Hexaqueue PyPI Reservation Publisher for Remaining Rate-Limited Packages
# ==============================================================================
# PyPI enforces a strict new-project creation rate limit (429 Too many new projects).
# This script iterates through all remaining unreserved packages, checks if they
# have already been registered, attempts upload with backoff, and reports status.
#
# Usage:
#   export UV_PUBLISH_TOKEN="pypi-..."
#   ./scripts/publish_remaining_pypi.sh
# ==============================================================================

set -euo pipefail

if [ -z "${UV_PUBLISH_TOKEN:-}" ]; then
  echo "::error:: UV_PUBLISH_TOKEN environment variable is not set."
  echo "Usage: UV_PUBLISH_TOKEN=\"pypi-...\" ./scripts/publish_remaining_pypi.sh"
  exit 1
fi

REMAINING_PACKAGES=(
  "hexaqueue-dashboard"
  "hexaqueue-github-runner"
  "hexaqueue-gitlab-runner"
  "hexaqueue-kueue"
  "hexaqueue-monitor"
  "hexaqueue-scanner"
  "hexaqueue-server"
  "hexaqueue-worker"
  "hexaqueue-workflow"
)

echo "🚀 Starting Hexaqueue remaining package PyPI publisher..."
echo "--------------------------------------------------------"

FAILED_COUNT=0
SUCCESS_COUNT=0

for pkg in "${REMAINING_PACKAGES[@]}"; do
  pkg_underscore="${pkg//-/_}"
  echo ""
  echo "==> Inspecting $pkg..."

  # Check if already available on PyPI
  if pip index versions "$pkg" 2>&1 | grep -q "Available versions:"; then
    echo "    ✅ $pkg is already published on PyPI. Skipping."
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    continue
  fi

  dist_files=(dist/${pkg_underscore}-0.0.0*.whl dist/${pkg_underscore}-0.0.0*.tar.gz dist/${pkg}-0.0.0*.whl dist/${pkg}-0.0.0*.tar.gz)
  # Filter only existing files
  existing_files=()
  for f in "${dist_files[@]}"; do
    if [ -f "$f" ]; then
      existing_files+=("$f")
    fi
  done

  if [ ${#existing_files[@]} -eq 0 ]; then
    echo "    ⚠️ No dist files found for $pkg in dist/. Run 'uv build' first."
    FAILED_COUNT=$((FAILED_COUNT + 1))
    continue
  fi

  echo "    📦 Publishing: ${existing_files[*]}..."
  if uv publish --token "$UV_PUBLISH_TOKEN" "${existing_files[@]}"; then
    echo "    🎉 Successfully published $pkg!"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    sleep 3
  else
    echo "    ⏳ Rate limit encountered or upload failed for $pkg. Try again after cooldown."
    FAILED_COUNT=$((FAILED_COUNT + 1))
  fi
done

echo ""
echo "--------------------------------------------------------"
echo "Publishing Summary: $SUCCESS_COUNT succeeded/skipped, $FAILED_COUNT pending rate-limit reset."
echo "--------------------------------------------------------"
