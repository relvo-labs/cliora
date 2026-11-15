#!/bin/sh
# Compose faces clients directly unless a verified host reverse proxy is configured.
set -eu
exec /usr/local/bin/cliora-trusted-proxies --allow-direct
