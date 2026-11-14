#!/bin/sh
# Diagnostic: check that a host answers. $1 is the target host.
echo "ping diagnostic for host: $1"
ping -c 2 "$1" 2>&1 || echo "(ping unavailable in sandbox)"
