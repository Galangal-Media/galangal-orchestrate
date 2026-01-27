#!/bin/bash
set -e

# Ensure data directory exists and has correct permissions
# This runs as root before switching to appuser
if [ ! -d "/data" ]; then
    mkdir -p /data
fi

# Change ownership to appuser (uid 1000)
chown -R appuser:appuser /data

# Switch to appuser and run the hub server
exec gosu appuser python -m galangal_hub.cli serve
