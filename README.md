# Quectel EM060K-GL Regional Unlock (`MCC 250` Russia & `MCC 432` Iran) for GL.iNet Mudi V2

**[English](#english) | [Русский](#русский)**

---

<a name="english"></a>

## English

Software-only regional unlock for the **Quectel EM060K-GL** cellular modem (`EM060KGLAAR01A11M2G_01.202.01.202`) to enable LTE registration in **Russia (`MCC 250`)** and **Iran (`MCC 432`)** without hardware disassembly, USB-to-M.2 adapters, soldering, or modifying bootloaders/IMEI/calibration partitions.

### What's Included
- **One-command automated SSH unlock & network setup script** for **GL.iNet Mudi V2 (`GL-E750V2`)**: [`unlock_mudi_em060k.sh`](./unlock_mudi_em060k.sh) (unlocks both **Russia `MCC 250`** and **Iran `MCC 432`** by default) and automated rollback script [`rollback_mudi_em060k.sh`](./rollback_mudi_em060k.sh).
- **Standalone static USB ADB client** [`src/mudi_adb.go`](./src/mudi_adb.go) (`bin/mudi_adb_mips_softfloat` compiled for `mips_24kc`), talking directly to the modem's USB `usbfs` endpoints inside OpenWrt and including a built-in `AT+QADBKEY` response calculator.
- **Full reverse-engineering & reproducible build toolkit** in [`tools/`](./tools/): Qualcomm `q6zip` v3.2 (`SDX12`) decompressor, exhaustive 4096-MCC patch verifier, and X.509 DER certificate chain / QPSA RSA-2048 signer (`modem.b01`, `modem.mdt`).

---

### 1. Symptoms of the Regional Lock (`MCC 250` & `MCC 432`)

Per Quectel PCN 2022113001, firmware `EM060KGLAAR01A11M2G_01.202.01.202` enforces a software PLMN block on **Russia (`MCC 250`)** and **Iran (`MCC 432`)** inside the Hexagon baseband image (`modem.b19`):

- The SIM card is read normally (`AT+CPIN?` → `+CPIN: READY`).
- Network scanning (`AT+COPS=?`) sees local LTE base stations in **Russia** (`25001` MTS, `25002` MegaFon, `25011` Yota, `25020` Tele2, `25099` Beeline) and **Iran** (`43211` MCI / Hamrah-e Aval, `43235` Irancell, `43220` Rightel).
- However, registration is rejected by the modem's NAS/REG layer (`+CEREG: 0,2` or `+CEREG: 0,0`, `AT+QENG="servingcell"` stuck in `"SEARCH"` or `"LIMSRV"`).
- Additionally, on **GL.iNet Mudi V2 (`GL-E750V2`)**, when LTE registration fails, the router UI may fall back to legacy `proto '3g'` (`/dev/ttyUSB3`), causing background `pppd` dial attempts (`ATD*99***1#`) to reset the radio scan loop every 60 seconds.

---

### 2. Quick Start (GL.iNet Mudi V2 / OpenWrt)

#### Requirements
- **GL.iNet Mudi V2 (`GL-E750V2`)** accessible over SSH (default `root@192.168.8.1`).
- **Quectel EM060K-GL** running `EM060KGLAAR01A11M2G_01.202.01.202` with hardware OEM Secure Boot disabled (`AT+QSECBOOT="status"` → `0`).

#### Run in One Command (from macOS or Linux)

```bash
git clone https://github.com/famence/quectel-em060k-gl-mcc250-unlock.git
cd quectel-em060k-gl-mcc250-unlock
chmod +x unlock_mudi_em060k.sh rollback_mudi_em060k.sh

# Usage: ./unlock_mudi_em060k.sh [root@router_ip] [carrier_apn] [both|ru]
# Default mode 'both' unlocks BOTH Russia (MCC 250) and Iran (MCC 432)

# Example for Russia (Yota):
./unlock_mudi_em060k.sh root@192.168.8.1 internet.yota

# Example for Iran (Irancell):
./unlock_mudi_em060k.sh root@192.168.8.1 mtnirancell
```

#### Common Carrier APNs
- **Iran (`MCC 432`)**:
  - **MCI (Hamrah-e Aval / `43211`)**: `mcinet`
  - **Irancell (`43235`)**: `mtnirancell`
  - **Rightel (`43220`)**: `RighTel`
  - **Shatel Mobile (`43208`)**: `shatelmobile`
- **Russia (`MCC 250`)**:
  - **Yota (`25011`)**: `internet.yota`
  - **MegaFon (`25002`)**: `internet`
  - **MTS (`25001`)**: `internet.mts.ru`
  - **Beeline (`25099`)**: `internet.beeline.ru`
  - **T2 / Tele2 (`25020`)**: `internet.tele2.ru`

#### What `unlock_mudi_em060k.sh` Does Automatically
1. Verifies exact firmware version (`EM060KGLAAR01A11M2G_01.202.01.202`) and `AT+QSECBOOT="status"` (`0`).
2. Queries `AT+QADBKEY?`, computes the MD5-crypt unlock key (`$1$<challenge>$` with secret `SH_adb_quectel`), unlocks ADB, and temporarily enables the USB ADB interface (`AT+QCFG="usbcfg",0x2C7C,0x030B,1,1,1,1,1,1,0`).
3. Triggers Quectel's internal NV golden backup (`AT+QPRTPARA=1`) and backs up the original `modem.b19`, `modem.b01`, `modem.b00`, `modem.mdt` both inside the modem's persistent storage (`/usrdata/cache/orig_fw_headers/`) and to your local computer (`backups/`).
4. Applies two 1-bit in-place patches in `/firmware/image/modem.b19` (`0x15b595`: `0x40` → `0x50` for **Russia `MCC 250`**, and `0x15ba67`: `0x78` → `0x7a` for **Iran `MCC 432`**), atomically replaces `/firmware/image/modem.b01` and `/firmware/image/modem.mdt`, verifies `sha256sum` of all three files, and remounts `/` read-only.
5. Reboots the modem and runs a watchdog check on the Hexagon DSP (`subsys1/state == ONLINE`, `crash_count == 0`), automatically rolling back if any error occurs.
6. Disables ADB (`AT+QCFG="usbcfg",0x2C7C,0x030B,1,1,1,1,1,0,0`), configures OpenWrt `proto 'qcm'` (`/dev/cdc-wdm0`) with your carrier's APN, and verifies LTE registration (`+CEREG: 0,1`).

#### Instant Rollback to Stock
```bash
./rollback_mudi_em060k.sh root@192.168.8.1
```

---

### 3. Technical Reverse Engineering (`MCC 250` & `MCC 432`)

#### 3.1. Baseband Architecture & `q6zip` v3.2 Compression
Inside the Quectel EM060K-GL (`Qualcomm Snapdragon X12 / SDX12`, `sdxnightjar`), an ARM Cortex-A7 application processor runs Linux `5.4.161-perf` (`ubi0:rootfs` mounted `ro` at `/`), while the cellular stack runs on the **Qualcomm Hexagon DSP** loaded from `/firmware/image/modem.{mdt,b00..b29}`.

Segment `modem.b19` (`8,593,408` bytes) contains the demand-paged Hexagon RO/Code section compressed with **Qualcomm `q6zip` v3.2** (`3,516` pages × `4,096` bytes = `14,401,536` bytes uncompressed).

#### 3.2. Disassembly of `quectel_check_current_plmn_is_need_forbidden` (`reg_sim.c`)
By parsing the QShrink 4.0 string database (`qdsp6m.qdb`) and decompressing all 3,516 pages of `modem.b19` ([`tools/q6zip_v32_decompress.py`](./tools/q6zip_v32_decompress.py)), we located `quectel_check_current_plmn_is_need_forbidden` at virtual address **`0xd021d634`..`0xd021d688`** (Page `541`, VA base `0xd021d000`):

- **QShrink4 ID `295251`** (`0xf8240a98`): `reg_sim.c:5469: quectel_check_current_plmn_is_need_forbidden MCC =%d%d%d` (Russia `MCC 250`)
- **QShrink4 ID `295252`** (`0xf8240aa0`): `reg_sim.c:5478: quectel_check_current_plmn_is_need_forbidden MCC =%d%d%d` (Iran `MCC 432`)
- **QShrink4 ID `295253`** (`0xf8240aa8`): `reg_sim.c:5506: Current PLMN is Russian PLMN and iran plmn,need Forbidden` (logged by wrapper `0xd021d68c`, which has 46 callers across `reg_mode.c`, `reg_sim.c`, `reg_state.c`)

```text
0xd021d634: 5a9c6402  { call 0xd0701e38            ; __save_r16_through_r19
0xd021d638: a09dc002    allocframe(#0x10) }
0xd021d63c: 8d204410  { r16 = extractu(r0, #4, #8) ; 3rd MCC digit (0..15)
0xd021d640: 8d004491    r17 = extractu(r0, #4, #4) } ; 2nd MCC digit (0..15)
0xd021d644: 760041f2  { r18 = and(r0, #0xf)        ; 1st MCC digit (0..15)
0xd021d648: 7800c000    r0 = #0 }                  ; default: 0 (allowed)

; --- Russia Check (MCC 250: r18 == 2, r17 == 5, r16 == 0) ---
0xd021d64c: 104ac210  { p0 = cmp.eq(r18, #2); if (!p0.new) jump:nt 0xd021d66c }
0xd021d650: 1049c50e  { p0 = cmp.eq(r17, #5); if (!p0.new) jump:nt 0xd021d66c }
0xd021d654: 1048400c  { p0 = cmp.eq(r16, #0); if (!p0.new) jump:nt 0xd021d66c }
0xd021d658: 0f8240a9  { immext(#0xf8240a80)
0xd021d65c: 3c00c298    r2 = ##0xf8240a98          ; QSR4: "MCC =%d%d%d" (reg_sim.c:5469)
0xd021d660: 28031201    r1 = #2; r3 = r18 }
0xd021d664: f9104000  { memw(r29+#0) = r16; memw(r29+#4) = r17 }
0xd021d668: 7800c020  { r0 = #1                    ; forbid PLMN (return 1)
0xd021d66c: 5ad45196    call 0xd076eb00 }          ; qsr4_msg_send_var

; --- Iran Check (MCC 432: r18 == 4, r17 == 3, r16 == 2) ---
0xd021d66c: 104ac40e  { p0 = cmp.eq(r18, #4); if (!p0.new) jump:nt 0xd021d688 }
0xd021d670: 1049c30c  { p0 = cmp.eq(r17, #3); if (!p0.new) jump:nt 0xd021d688 }
0xd021d674: 1048c20a  { p0 = cmp.eq(r16, #2); if (!p0.new) jump:nt 0xd021d688 }
0xd021d678: 5a9c66e4  { call 0xd076eb00 ...        ; QSR4: "MCC =%d%d%d" (reg_sim.c:5478)
0xd021d684: 7800c020  { r0 = #1 }                  ; forbid PLMN (return 1)
0xd021d688: 589ce3e0  { jump 0xd0701e48 }          ; epilogue, return r0
```

#### 3.3. Surgical 1-Bit Patches in `q6zip` Stream (Zero Side Effects)
Tracing the `q6zip` v3.2 decoder on Page `541` ([`tools/verify_patch_page541.py`](./tools/verify_patch_page541.py)) reveals how both instructions are encoded:

1. **Russia (`MCC 250`) — `0xd021d654` (`0x1048400c`)**:
   - Stored as raw 32-bit `LITERAL[110]` at file offset **`0x15b594`** (`1,422,740`).
   - Flipping 1 bit at byte **`0x15b595`** (`1,422,741`) from `0x40` to `0x50` changes `0x1048400c` → `0x1048500c` (`p0 = cmp.eq(r16, #16)`).
2. **Iran (`MCC 432`) — `0xd021d674` (`0x1048c20a`)**:
   - Encoded via `PATCH16_0_NEW(r25=-8, val16=0xc20a, bit_pos=5229)`.
   - Flipping 1 bit at `bit_pos=5241` (file offset **`0x15ba67`**, dec `1,423,975`) from `0x78` to `0x7a` changes `val16` from `0xc20a` to `0xd20a`, producing `0x1048d20a` (`p0 = cmp.eq(r16, #18)`).

Since `r16 = extractu(r0, #4, #8)` is a 4-bit unsigned integer (`0 <= r16 <= 15`), both `r16 == 16` and `r16 == 18` are **impossible for all 4,096 inputs (`0x000..0xfff`)**. Neither country check is reassigned to another country, and no other instruction in Page `541` or across the entire 3,516-page image is affected.

---

<a name="русский"></a>

## Русский

Программная разблокировка сотового модема **Quectel EM060K-GL** (`EM060KGLAAR01A11M2G_01.202.01.202`) для работы в сетях LTE **России (`MCC 250`)** и **Ирана (`MCC 432`)** без разборки роутера, переходников, пайки и модификации разделов загрузчика/IMEI/калибровок.

### Состав репозитория
- **Автоматический скрипт разблокировки и настройки по SSH** для роутера **GL.iNet Mudi V2 (`GL-E750V2`)** — [`unlock_mudi_em060k.sh`](./unlock_mudi_em060k.sh) (по умолчанию снимает блокировку сразу для **России `MCC 250`** и **Ирана `MCC 432`**) и скрипт отката [`rollback_mudi_em060k.sh`](./rollback_mudi_em060k.sh).
- **Автономный статический USB ADB-клиент** [`src/mudi_adb.go`](./src/mudi_adb.go) (`bin/mudi_adb_mips_softfloat` под `mips_24kc`), работающий напрямую поверх Linux `usbfs` внутри роутера и включающий генератор ключей `AT+QADBKEY`.
- **Полный инструментарий реверс-инжиниринга и пересборки образов** в [`tools/`](./tools/): распаковщик `q6zip` v3.2 (`SDX12`), верификатор патча на всех 4096 значениях MCC и генератор цепочки сертификатов X.509 DER / подписи QPSA RSA-2048 (`modem.b01`, `modem.mdt`).

---

### 1. Быстрый старт (GL.iNet Mudi V2 / OpenWrt)

```bash
git clone https://github.com/famence/quectel-em060k-gl-mcc250-unlock.git
cd quectel-em060k-gl-mcc250-unlock
chmod +x unlock_mudi_em060k.sh rollback_mudi_em060k.sh

# Формат: ./unlock_mudi_em060k.sh [root@IP_роутера] [APN_оператора] [both|ru]
# По умолчанию режим 'both' разблокирует и Россию (MCC 250), и Иран (MCC 432)

# Пример для России (Yota):
./unlock_mudi_em060k.sh root@192.168.8.1 internet.yota

# Пример для Ирана (Irancell):
./unlock_mudi_em060k.sh root@192.168.8.1 mtnirancell
```

#### APN основных операторов
- **Россия (`MCC 250`)**:
  - **Yota (`25011`)**: `internet.yota`
  - **МегаФон (`25002`)**: `internet`
  - **МТС (`25001`)**: `internet.mts.ru`
  - **Билайн (`25099`)**: `internet.beeline.ru`
  - **T2 / Tele2 (`25020`)**: `internet.tele2.ru`
- **Иран (`MCC 432`)**:
  - **MCI / Hamrah-e Aval (`43211`)**: `mcinet`
  - **Irancell (`43235`)**: `mtnirancell`
  - **Rightel (`43220`)**: `RighTel`
  - **Shatel Mobile (`43208`)**: `shatelmobile`

#### Откат к заводскому состоянию
```bash
./rollback_mudi_em060k.sh root@192.168.8.1
```

---

### 2. Таблица модификаций и контрольных сумм (`EM060KGLAAR01A11M2G_01.202.01.202`)

| Смещение в `modem.b19` | Назначение | Заводской байт | Новый байт | Изменение инструкции Hexagon |
| :--- | :--- | :--- | :--- | :--- |
| `0x15b595` (dec `1422741`) | **Россия (`MCC 250`)** (`0xd021d654`) | `0x40` | `0x50` | `cmp.eq(r16, #0)` → `cmp.eq(r16, #16)` |
| `0x15ba67` (dec `1423975`) | **Иран (`MCC 432`)** (`0xd021d674`) | `0x78` | `0x7a` | `cmp.eq(r16, #2)` → `cmp.eq(r16, #18)` |

| Вариант | `modem.b19` SHA-256 | `modem.b01` SHA-256 | `modem.mdt` SHA-256 |
| :--- | :--- | :--- | :--- |
| **Stock (Заводской)** | `429e4daa890a2b8c4c2aaa0456db37264db41fe1932b46d1659af1483c85631c` | `a4844208578d7664b4292bde3dfef0bec18fed43a953ee04596cc6a855220763` | `963b6d655f3758f22fc4cf484c48471a1433b31bd58a7d85729cbf4c2f96e32c` |
| **Russia + Iran (`both`)** | `e8ea988f4006d183a6d9e2f07c5d5c8756936086cde9458bf7f7684057ec0279` | `01eabc0f8b729a6ef93d11eaa58463b1ce9aafe7de3073d4cb619b52ee3d7321` | `f48168777b29162e0d73da6795c43fcdcb8566b6a40c01b6b13ceb4af2e9c445` |
| **Russia Only (`ru`)** | `94561e4a0c2257aaa7faf652135c3b6327e300cca4c336dff0591e23e2216d07` | `0d65dfe2dfecec1612dca7ed40caff1c04920fcf0371fb7e7990957017cedcda` | `1652c27907ecd5133050c847c4631e72b2c9acdedc6b8b1b2b712dd050507314` |

---

### Благодарности / Credits
- Цикл статей Льва Ларина ([@Tigramaan](https://habr.com/ru/users/Tigramaan/)) на Хабре о снятии блокировки `MCC 250` на модемах Quectel (`EG25-GC`, `EG25-G`, `RG255C-GL`).
- Исследование механизма `AT+QADBKEY` от Ondřej Jirman (Megi).
