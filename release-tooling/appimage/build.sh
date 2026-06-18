#!/usr/bin/env bash
# Host-side orchestrator: builds the reproducible image and runs the container
# build, dropping the finished AppImage into ./releases/.
#
# The repo is mounted read-only; all build artifacts are written inside the
# container, so your working tree stays clean.
#
# Docker access: if your user is not in the `docker` group, run this with sudo
# or set DOCKER="sudo docker":
#     DOCKER="sudo docker" ./release-tooling/appimage/build.sh
set -euo pipefail

DOCKER="${DOCKER:-docker}"
IMAGE="superpaper-appimage-builder"

# Repo root (this script lives in release-tooling/appimage/).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

VERSION="$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' superpaper/__version__.py)"
if [ -z "${VERSION}" ]; then
    echo "error: could not read version from superpaper/__version__.py" >&2
    exit 1
fi
echo "==> Building Superpaper ${VERSION} AppImage"

${DOCKER} build -t "${IMAGE}" release-tooling/appimage

mkdir -p releases
${DOCKER} run --rm \
    -v "${REPO_ROOT}:/src:ro" \
    -v "${REPO_ROOT}/releases:/out" \
    "${IMAGE}" \
    /src/release-tooling/appimage/build_in_container.sh "${VERSION}"

echo "==> AppImage written to releases/Superpaper-${VERSION}-x86_64.AppImage"
