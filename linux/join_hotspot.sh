#!/usr/bin/env bash
# Join the laptop's Wi-Fi hotspot from the UNO Q Linux side (NetworkManager).
#
# Usage: ./join_hotspot.sh "<SSID>" "<PASSWORD>"
#
# Run once on the board after enabling Mobile hotspot on the laptop.
# Marks the connection autoconnect so the board rejoins at boot.
set -euo pipefail

SSID="${1:?usage: join_hotspot.sh SSID PASSWORD}"
PASS="${2:?usage: join_hotspot.sh SSID PASSWORD}"

nmcli device wifi rescan || true
nmcli device wifi connect "$SSID" password "$PASS"
nmcli connection modify "$SSID" connection.autoconnect yes
nmcli -g IP4.GATEWAY device show | head -n1   # should print 192.168.137.1
