#!/bin/bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

# Try graceful shutdown first (SIGINT so mass can do gpio notify off)
for name in cam reader mass lidar mcp xmit; do
	pkill -INT -f "$SCRIPT_DIR/$name"
done

# Give them a moment to handle signals and close sockets
sleep 0.5

# Anything still alive gets a TERM
for name in cam reader mass lidar mcp xmit; do
	pkill -TERM -f "$SCRIPT_DIR/$name"
done
