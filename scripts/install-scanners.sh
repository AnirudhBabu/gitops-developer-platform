#!/usr/bin/env bash
# Installs the security scanners used by .github/workflows/security.yml.
#
# Supply-chain hygiene: every binary is pinned to an exact version and its
# SHA-256 is hard-coded here, so a tampered or swapped release asset fails
# the build instead of running in CI. Bump a version by updating both the
# version and the hash from the project's published checksums file.
#
# Usage: scripts/install-scanners.sh [install_dir]   (default: ./.bin)
set -euo pipefail

INSTALL_DIR="${1:-.bin}"
mkdir -p "$INSTALL_DIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

install_tool() {
  local name="$1" url="$2" sha256="$3"
  echo "==> $name"
  curl -sSfL --retry 3 -o "$WORK/$name.tar.gz" "$url"
  echo "$sha256  $WORK/$name.tar.gz" | sha256sum --check --strict -
  tar -xzf "$WORK/$name.tar.gz" -C "$WORK" "$name"
  install -m 0755 "$WORK/$name" "$INSTALL_DIR/$name"
}

GITLEAKS_VERSION=8.30.1
install_tool gitleaks \
  "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
  551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb

TRIVY_VERSION=0.76.0
install_tool trivy \
  "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
  e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7

CONFTEST_VERSION=0.71.1
install_tool conftest \
  "https://github.com/open-policy-agent/conftest/releases/download/v${CONFTEST_VERSION}/conftest_${CONFTEST_VERSION}_Linux_x86_64.tar.gz" \
  c3f6b2a753bd56e377a1e51a95ae3e057f926f2e9139f7d5b5dfbbaf810f7985

echo "Installed to $INSTALL_DIR:"
"$INSTALL_DIR/gitleaks" version
"$INSTALL_DIR/trivy" --version | head -1
"$INSTALL_DIR/conftest" --version | head -1
