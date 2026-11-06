#!/usr/bin/env bash
# ==============================================================================
# Automated Software Unlock for Quectel EM060K-GL (Russia MCC 250 & Iran MCC 432)
# Target Device : GL.iNet Mudi V2 (GL-E750V2) with Quectel EM060K-GL
# Firmware      : EM060KGLAAR01A11M2G_01.202.01.202
#
# Usage:
#   ./unlock_mudi_em060k.sh [ssh_target] [apn] [both|ru]
# Examples:
#   ./unlock_mudi_em060k.sh root@192.168.8.1 internet.yota
#   ./unlock_mudi_em060k.sh root@192.168.8.1 mtnirancell
# ==============================================================================
set -euo pipefail

ROUTER="${1:-root@192.168.8.1}"
APN="${2:-internet.yota}"
MODE="${3:-both}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/backups/$(date +%Y%m%d_%H%M%S)"

ADB_BIN="${SCRIPT_DIR}/bin/mudi_adb_mips_softfloat"
if [ "$MODE" = "ru" ]; then
    PATCH_B01="${SCRIPT_DIR}/patched/EM060KGLAAR01A11M2G_01.202.01.202/modem.b01"
    PATCH_MDT="${SCRIPT_DIR}/patched/EM060KGLAAR01A11M2G_01.202.01.202/modem.mdt"
    EXP_B19="94561e4a0c2257aaa7faf652135c3b6327e300cca4c336dff0591e23e2216d07"
    EXP_B01="0d65dfe2dfecec1612dca7ed40caff1c04920fcf0371fb7e7990957017cedcda"
    EXP_MDT="1652c27907ecd5133050c847c4631e72b2c9acdedc6b8b1b2b712dd050507314"
else
    PATCH_B01="${SCRIPT_DIR}/patched/EM060KGLAAR01A11M2G_01.202.01.202/ru_ir/modem.b01"
    PATCH_MDT="${SCRIPT_DIR}/patched/EM060KGLAAR01A11M2G_01.202.01.202/ru_ir/modem.mdt"
    EXP_B19="e8ea988f4006d183a6d9e2f07c5d5c8756936086cde9458bf7f7684057ec0279"
    EXP_B01="01eabc0f8b729a6ef93d11eaa58463b1ce9aafe7de3073d4cb619b52ee3d7321"
    EXP_MDT="f48168777b29162e0d73da6795c43fcdcb8566b6a40c01b6b13ceb4af2e9c445"
fi

if [ ! -f "$ADB_BIN" ] || [ ! -f "$PATCH_B01" ] || [ ! -f "$PATCH_MDT" ]; then
    echo "ERROR: Required files missing in ${SCRIPT_DIR}/{bin,patched}." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "============================================================"
echo "Quectel EM060K-GL Unlock Utility (Russia MCC 250 / Iran MCC 432)"
echo "Router SSH  : ${ROUTER}"
echo "Target APN  : ${APN}"
echo "Unlock Mode : ${MODE} (both = Russia 250 + Iran 432, ru = Russia 250)"
echo "Backup Dir  : ${BACKUP_DIR}"
echo "============================================================"

echo "[1/5] Uploading mudi_adb and patched MBN headers to ${ROUTER}:/tmp/ ..."
scp -O "$ADB_BIN" "${ROUTER}:/tmp/mudi_adb"
scp -O "$PATCH_B01" "${ROUTER}:/tmp/modem.b01"
scp -O "$PATCH_MDT" "${ROUTER}:/tmp/modem.mdt"

echo "[2/5] Running diagnostics, ADB unlock, backup, and patch on router..."
ssh "$ROUTER" "APN='${APN}' MODE='${MODE}' EXP_B19='${EXP_B19}' EXP_B01='${EXP_B01}' EXP_MDT='${EXP_MDT}' sh -s" << 'EOF'
set -e

chmod +x /tmp/mudi_adb
mkdir -p /tmp/modem_backup

# Stop interfering background pppd/cron retries while working on the modem
/etc/init.d/cron stop 2>/dev/null || true
ubus call network.interface.modem_1_1_2 down 2>/dev/null || true

echo "--- Checking Firmware Version & Secure Boot State ---"
FW_VER=$(gl_modem -B 1-1.2 AT 'AT+QGMR' | tr -d '\r' | grep 'EM060K' || true)
SEC_STAT=$(gl_modem -B 1-1.2 AT 'AT+QSECBOOT="status"' | tr -d '\r' | grep '+QSECBOOT:' || true)
ROOT_HASH=$(gl_modem -B 1-1.2 AT 'AT+QSECBOOT="roothash"' | tr -d '\r' | grep '+QSECBOOT:' || true)

echo "Detected Firmware : $FW_VER"
echo "Secure Boot Status: $SEC_STAT"
echo "Root Key Hash     : $ROOT_HASH"

if [ "$FW_VER" != "EM060KGLAAR01A11M2G_01.202.01.202" ]; then
    echo "ERROR: Expected firmware EM060KGLAAR01A11M2G_01.202.01.202, got '$FW_VER'. Aborting."
    exit 1
fi

case "$SEC_STAT" in
    *'"status",0'*) ;;
    *)
        echo "ERROR: Hardware Secure Boot is enabled ($SEC_STAT). Aborting."
        exit 1
        ;;
esac

# Check if ADB USB interface (ff/42/01) is already active
ADB_READY=0
for d in /sys/bus/usb/devices/1-1.2*; do
    if [ -f "$d/bInterfaceClass" ]; then
        c=$(cat "$d/bInterfaceClass" 2>/dev/null || true)
        s=$(cat "$d/bInterfaceSubClass" 2>/dev/null || true)
        p=$(cat "$d/bInterfaceProtocol" 2>/dev/null || true)
        if [ "$c" = "ff" ] && [ "$s" = "42" ] && [ "$p" = "01" ]; then
            ADB_READY=1
        fi
    fi
done

if [ "$ADB_READY" = "0" ]; then
    echo "--- Unlocking Modem ADB via AT+QADBKEY ---"
    CHALLENGE=$(gl_modem -B 1-1.2 AT 'AT+QADBKEY?' | tr -d '\r' | awk -F': ' '/\+QADBKEY:/ {print $2}')
    if [ -z "$CHALLENGE" ]; then
        echo "ERROR: Failed to read AT+QADBKEY? challenge from modem."
        exit 1
    fi
    ADB_KEY=$(/tmp/mudi_adb qadbkey "$CHALLENGE")
    echo "Challenge: $CHALLENGE -> Key: $ADB_KEY"
    gl_modem -B 1-1.2 AT "AT+QADBKEY=\"${ADB_KEY}\""
    gl_modem -B 1-1.2 AT 'AT+QCFG="usbcfg",0x2C7C,0x030B,1,1,1,1,1,1,0'
    gl_modem -B 1-1.2 AT 'AT+CFUN=1,1' || true

    echo "Waiting for modem reboot and ADB USB interface enumeration..."
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
                    ADB_READY=1
                    break 2
                fi
            fi
        done
        i=$((i + 1))
    done
    sleep 3
    /etc/init.d/cron stop 2>/dev/null || true
    ubus call network.interface.modem_1_1_2 down 2>/dev/null || true
fi

if [ "$ADB_READY" != "1" ]; then
    echo "ERROR: Modem ADB USB interface (ff/42/01) did not appear."
    exit 1
fi

echo "--- Triggering Quectel Golden NV Backup (AT+QPRTPARA=1) ---"
gl_modem -B 1-1.2 AT 'AT+QPRTPARA=1' || true

echo "--- Backing up Original Modem Headers to /usrdata/cache/orig_fw_headers & Router ---"
/tmp/mudi_adb '
set -e
mkdir -p /usrdata/cache/orig_fw_headers /usrdata/cache/patched
if [ ! -f /usrdata/cache/orig_fw_headers/modem.b19 ]; then
    cp -f /firmware/image/modem.mdt /usrdata/cache/orig_fw_headers/modem.mdt
    cp -f /firmware/image/modem.b00 /usrdata/cache/orig_fw_headers/modem.b00
    cp -f /firmware/image/modem.b01 /usrdata/cache/orig_fw_headers/modem.b01
    cp -f /firmware/image/modem.b19 /usrdata/cache/orig_fw_headers/modem.b19
    sync
fi
sha256sum /usrdata/cache/orig_fw_headers/modem.*
'

/tmp/mudi_adb pull /usrdata/cache/orig_fw_headers/modem.mdt /tmp/modem_backup/modem.mdt.orig
/tmp/mudi_adb pull /usrdata/cache/orig_fw_headers/modem.b00 /tmp/modem_backup/modem.b00.orig
/tmp/mudi_adb pull /usrdata/cache/orig_fw_headers/modem.b01 /tmp/modem_backup/modem.b01.orig
tar -czf /tmp/modem_headers_backup.tar.gz -C /tmp modem_backup

echo "--- Pushing Patched Headers and Applying Patch in /firmware/image/modem.b19 ---"
/tmp/mudi_adb push /tmp/modem.b01 /usrdata/cache/patched/modem.b01
/tmp/mudi_adb push /tmp/modem.mdt /usrdata/cache/patched/modem.mdt

/tmp/mudi_adb "
set -e
s_b19=\$(sha256sum /usrdata/cache/orig_fw_headers/modem.b19 | awk '{print \$1}')
if [ \"\$s_b19\" != '429e4daa890a2b8c4c2aaa0456db37264db41fe1932b46d1659af1483c85631c' ]; then
    echo \"ERROR: Unexpected stock modem.b19 SHA-256 (\$s_b19). Aborting.\"
    exit 1
fi

mount -o remount,rw /

rollback_and_exit() {
    echo 'ROLLBACK TRIGGERED! Restoring stock files...'
    printf '\x40' | dd of=/firmware/image/modem.b19 bs=1 seek=1422741 count=1 conv=notrunc 2>/dev/null || true
    printf '\x78' | dd of=/firmware/image/modem.b19 bs=1 seek=1423975 count=1 conv=notrunc 2>/dev/null || true
    cp -f /usrdata/cache/orig_fw_headers/modem.b01 /firmware/image/modem.b01 || true
    cp -f /usrdata/cache/orig_fw_headers/modem.mdt /firmware/image/modem.mdt || true
    chmod 644 /firmware/image/modem.b19 /firmware/image/modem.b01 /firmware/image/modem.mdt || true
    sync
    mount -o remount,ro / || true
    exit 1
}

# Reset both bytes to stock first in case switching between 'ru' and 'both' modes
printf '\x40' | dd of=/firmware/image/modem.b19 bs=1 seek=1422741 count=1 conv=notrunc || rollback_and_exit
printf '\x78' | dd of=/firmware/image/modem.b19 bs=1 seek=1423975 count=1 conv=notrunc || rollback_and_exit

# Patch Russia MCC 250 (0x15b595: 0x40 -> 0x50)
printf '\x50' | dd of=/firmware/image/modem.b19 bs=1 seek=1422741 count=1 conv=notrunc || rollback_and_exit
if [ '${MODE}' = 'both' ]; then
    # Patch Iran MCC 432 (0x15ba67: 0x78 -> 0x7a)
    printf '\x7a' | dd of=/firmware/image/modem.b19 bs=1 seek=1423975 count=1 conv=notrunc || rollback_and_exit
fi

cp -f /usrdata/cache/patched/modem.b01 /firmware/image/modem.b01.tmp || rollback_and_exit
chmod 644 /firmware/image/modem.b01.tmp || rollback_and_exit
mv -f /firmware/image/modem.b01.tmp /firmware/image/modem.b01 || rollback_and_exit

cp -f /usrdata/cache/patched/modem.mdt /firmware/image/modem.mdt.tmp || rollback_and_exit
chmod 644 /firmware/image/modem.mdt.tmp || rollback_and_exit
mv -f /firmware/image/modem.mdt.tmp /firmware/image/modem.mdt || rollback_and_exit

rm -rf /usrdata/cache/patched
sync

new_b19=\$(sha256sum /firmware/image/modem.b19 | awk '{print \$1}')
new_b01=\$(sha256sum /firmware/image/modem.b01 | awk '{print \$1}')
new_mdt=\$(sha256sum /firmware/image/modem.mdt | awk '{print \$1}')

if [ \"\$new_b19\" != '${EXP_B19}' ] || \
   [ \"\$new_b01\" != '${EXP_B01}' ] || \
   [ \"\$new_mdt\" != '${EXP_MDT}' ]; then
    echo 'ERROR: Post-write SHA-256 mismatch!'
    rollback_and_exit
fi

mount -o remount,ro /
echo 'All 3 files patched and verified successfully.'
"

echo "--- Rebooting Modem to Verify Hexagon DSP State ---"
gl_modem -B 1-1.2 AT "AT+CGDCONT=1,\"IPV4V6\",\"${APN}\"" || true
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

DSP_STATE=$(/tmp/mudi_adb 'cat /sys/devices/platform/4080000.qcom,mss/subsys1/state' | tr -d '\r\n ')
echo "Hexagon DSP State: $DSP_STATE"
if [ "$DSP_STATE" != "ONLINE" ]; then
    echo "ERROR: DSP did not come ONLINE. Rolling back..."
    /tmp/mudi_adb '
    mount -o remount,rw /
    printf "\x40" | dd of=/firmware/image/modem.b19 bs=1 seek=1422741 count=1 conv=notrunc
    printf "\x78" | dd of=/firmware/image/modem.b19 bs=1 seek=1423975 count=1 conv=notrunc
    cp -f /usrdata/cache/orig_fw_headers/modem.b01 /firmware/image/modem.b01
    cp -f /usrdata/cache/orig_fw_headers/modem.mdt /firmware/image/modem.mdt
    sync
    mount -o remount,ro /
    '
    exit 1
fi

echo "--- Disabling Modem ADB & Configuring Router QCM Interface (${APN}) ---"
gl_modem -B 1-1.2 AT 'AT+QCFG="usbcfg",0x2C7C,0x030B,1,1,1,1,1,0,0'
gl_modem -B 1-1.2 AT 'AT+CFUN=1,1' || true
sleep 6
i=0
while [ $i -lt 35 ]; do
    sleep 1
    if [ -e /dev/cdc-wdm0 ] && [ -e /dev/ttyUSB2 ]; then
        break
    fi
    i=$((i + 1))
done
sleep 4

uci set network.modem_1_1_2=interface
uci set network.modem_1_1_2.proto='qcm'
uci set network.modem_1_1_2.device='/dev/cdc-wdm0'
uci set network.modem_1_1_2.node='1-1.2:1.4'
uci set network.modem_1_1_2.apn="${APN}"
uci set network.modem_1_1_2.pdp='IPV4V6'
uci set network.modem_1_1_2.auth='NONE'
uci set network.modem_1_1_2.metric='40'
uci set network.modem_1_1_2.disabled='0'
uci delete network.modem_1_1_2.service 2>/dev/null || true
uci commit network

uci set glmodem.modem_1_1_2.dev='wwan0' 2>/dev/null || true
uci commit glmodem 2>/dev/null || true

/etc/init.d/network reload
ifup modem_1_1_2
/etc/init.d/cron start 2>/dev/null || true

echo "--- Waiting for LTE Registration (AT+CEREG?) ---"
j=0
while [ $j -lt 15 ]; do
    sleep 2
    CEREG=$(gl_modem -B 1-1.2 AT 'AT+CEREG?' | grep '+CEREG:' || true)
    echo "Check $((j+1)): $CEREG"
    case "$CEREG" in
        *",1"*|*",5"*)
            echo "Registered in LTE network!"
            break
            ;;
    esac
    j=$((j + 1))
done

gl_modem -B 1-1.2 AT 'AT+COPS?'
gl_modem -B 1-1.2 AT 'AT+QNWINFO'
gl_modem -B 1-1.2 AT 'AT+QENG="servingcell"'
EOF

echo "[3/5] Downloading modem header backups to ${BACKUP_DIR}/ ..."
scp -O "${ROUTER}:/tmp/modem_headers_backup.tar.gz" "${BACKUP_DIR}/modem_headers_backup.tar.gz"

echo "[4/5] Cleaning temporary files in ${ROUTER}:/tmp/ ..."
ssh "$ROUTER" "rm -f /tmp/mudi_adb /tmp/modem.b01 /tmp/modem.mdt /tmp/modem_headers_backup.tar.gz && rm -rf /tmp/modem_backup"

echo "[5/5] Done! Unlock completed and backup saved in ${BACKUP_DIR}/modem_headers_backup.tar.gz"
