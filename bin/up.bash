#!/bin/bash
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
"$SCRIPT_DIR/cam" &
"$SCRIPT_DIR/readerInit" &
"$SCRIPT_DIR/massInit" &
"$SCRIPT_DIR/lidar" &
"$SCRIPT_DIR/mcp" &
"$SCRIPT_DIR/xmit" &
