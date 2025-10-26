#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

readonly IMAGE_NAME="fedow"
readonly DOCKER_USER="tibillet"

if [[ -f VERSION ]]; then
  VERSION="$(< VERSION)"
else
  echo "VERSION file not found next to this script" >&2
  exit 1
fi

git checkout main
git pull

docker build -t "$DOCKER_USER/$IMAGE_NAME:latest" -t "$DOCKER_USER/$IMAGE_NAME:$VERSION" .

docker push "$DOCKER_USER/$IMAGE_NAME:latest"
docker push "$DOCKER_USER/$IMAGE_NAME:$VERSION"
