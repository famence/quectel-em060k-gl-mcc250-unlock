#!/usr/bin/env bash
# ==============================================================================
# Automated Software Rollback for Quectel EM060K-GL on GL.iNet Mudi V2
# Restores stock /firmware/image/modem.{b19,b01,mdt} from /usrdata/cache/orig_fw_headers
#
# Usage:
#   ./rollback_mudi_em060k.sh [ssh_target]
# ==============================================================================
set -euo pipefail

ROUTER="${1:-root@192.168.8.1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADB_BIN="${SCRIPT_DIR}/bin/mudi_adb_mips_softfloat"

echo "Uploading mudi_adb to ${ROUTER}:/tmp/mudi_adb ..."
scp -O "$ADB_BIN" "${ROUTER}:/tmp/mudi_adb"

echo "Restoring stock modem firmware files on ${ROUTER} ..."
ssh "$ROUTER" "sh -s" << 'EOF'
set -e
chmod +x /tmp/mudi_adb

/etc/init.d/cron stop 2>/dev/null || true
ubus call network.interface.modem_1_1_2 down 2>/dev/null || true

CHALLENGE=$(gl_modem -B 1-1.2 AT 'AT+QADBKEY?' | tr -d '\r' | awk -F': ' '/\+QADBKEY:/ {print $2}')
ADB_KEY=$(/tmp/mudi_adb qadbkey "$CHALLENGE")
gl_modem -B 1-1.2 AT "AT+QADBKEY=\"${ADB_KEY}\""
gl_modem -B 1-1.2 AT 'AT+QCFG="usbcfg",0x2C7C,0x030B,1,1,1,1,1,1,0'
gl_modem -B 1-1.2 AT 'AT+CFUN=1,1' || true

sleep 6
i=0
while [ $i -lt 40 ]; do
    sleep 1
    for d in /sys/bus/usb/devices/1-1.2*; do
        if [ -f "$d/bInterfaceClass" ]; then
            c=$(cat "$d/bInterfaceClass" 2>/dev/null || true)
            s=$(cat "$d/bInterfaceSubClass" 2>/dev/null || true)
            p=$(cat "$d/bInterfaceProtocol" 2>/dev/null || true)
            if [ "$c" = "ff" ] && [ "$s" = "42" ] && [ "$p" = "01" ]; then
                break 2
            fi
        fi
    done
    i=$((i + 1))
done
sleep 3

/tmp/mudi_adb '
set -e
mount -o remount,rw /
printf "\x40" | dd of=/firmware/image/modem.b19 bs=1 seek=1422741 count=1 conv=notrunc
cp -f /usrdata/cache/orig_fw_headers/modem.b01 /firmware/image/modem.b01
cp -f /usrdata/cache/orig_fw_headers/modem.mdt /firmware/image/modem.mdt
chmod 644 /firmware/image/modem.b19 /firmware/image/modem.b01 /firmware/image/modem.mdt
sync
sha256sum /firmware/image/modem.b19 /firmware/image/modem.b01 /firmware/image/modem.mdt
mount -o remount,ro /
'

gl_modem -B 1-1.2 AT 'AT+QCFG="usbcfg",0x2C7C,0x030B,1,1,1,1,1,0,0'
gl_modem -B 1-1.2 AT 'AT+CFUN=1,1' || true
rm -f /tmp/mudi_adb
/etc/init.d/cron start 2>/dev/null || true
echo "Stock firmware restored successfully."
EOF
