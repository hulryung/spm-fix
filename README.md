# ARA 87 2.4G dongle updater for macOS

`ara87_dongle_update.py` flashes the firmware of the SPM ARA 87 2.4 GHz dongle (Ingchips ING91680C, VID `0x36B0` / PID `0x3002`) from macOS. SPM ships the update only as a Windows `.exe`.

The script doesn't convert anything. It pulls the firmware image straight out of the vendor's Windows updater `.exe` and sends it over USB HID using the same IAP protocol. The protocol was worked out by disassembling that updater. No firmware is included in this repository. You need the vendor `.exe`.

## Requirements

```sh
brew install hidapi
python3 -m venv venv && venv/bin/pip install hid
```

## Usage

```sh
# check the image and build every frame without touching the device
venv/bin/python ara87_dongle_update.py --exe "(동글)ARA 87_2.4G_V0101_260331.exe" --dry-run

# flash (asks for confirmation; keep the dongle plugged in until it finishes)
DYLD_LIBRARY_PATH=/opt/homebrew/lib venv/bin/python ara87_dongle_update.py --exe "(동글)ARA 87_2.4G_V0101_260331.exe"
```

The dongle's current firmware version is the USB `bcdDevice` value (for example `0x0101` = V0101). The script prints it before flashing.

## Keyboard (wired) firmware

The keyboard itself needs no tool:

1. Turn the power switch off.
2. Hold **ESC** while you plug in the USB cable. A USB drive appears.
3. Drag and drop the `.bin` file onto it.

### 키보드 펌웨어 업데이트 (한국어)

키보드 본체는 별도 프로그램 없이 Mac에서도 업데이트할 수 있습니다.

1. 키보드 뒷면의 전원 스위치를 **OFF**로 둡니다.
2. **ESC** 키를 누른 채로 USB 케이블을 컴퓨터에 연결합니다. 그러면 USB 저장소 장치가 나타납니다.
3. 펌웨어 파일(예: `(유선)ARA 87_V0106_260811.bin`)을 그 저장소에 드래그 앤 드롭합니다.

## Protocol summary

| Layer | Format |
|---|---|
| HID frame (64 B, report ID `0x3F`, usage page `0xFF00`) | `3F AA 00` · u16 LE (packets remaining, bit 15 = first) · u16 LE length (≤ 56) · data · XOR of bytes [2..] |
| Message | cmd · u16 LE length · payload · CRC16/MODBUS (big endian) |
| `A0` header | 128-byte IAP header (`INGCHIPS…`) |
| `A1` block | u16 block number (`0xFFFF` = last) · u32 offset · 256-byte block |
| `A4` finish | u16 reboot delay in ms |
| Reply | `B0` · status (0 = OK, `0xE0`–`0xFB` = error codes) · … |

## Disclaimer

This is an unofficial tool and you use it at your own risk. It is not affiliated with SPM.
