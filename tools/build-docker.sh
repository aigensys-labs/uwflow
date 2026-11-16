#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCK=${ROOT}/docker/Dockerfile 

docker build -t aigensys/uwflow-runtime:1.2.2 -f ${DOCK} .