#!/bin/sh
set -eu

node ops/configure-metrics-gateway.mjs
exec pnpm run start
