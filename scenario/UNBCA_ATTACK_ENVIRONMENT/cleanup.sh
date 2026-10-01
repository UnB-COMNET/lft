#!/bin/bash
echo "[LFT] Cleaning up scenario containers and network interfaces..."
docker rm -f $(docker ps -aq) 2>/dev/null || true
ip link del h_brint 2>/dev/null || true
ip link del h_brex 2>/dev/null || true
rm -rf /var/run/netns/* 2>/dev/null || true
echo "[LFT] Cleanup completed successfully."
