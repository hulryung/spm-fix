# ARA 87 2.4G dongle updater for macOS

`ara87_dongle_update.py` flashes the firmware of the SPM ARA 87 2.4 GHz dongle (Ingchips ING91680C, VID `0x36B0` / PID `0x3002`) from macOS. SPM ships the update only as a Windows `.exe`.

The script doesn't convert anything. It pulls the firmware image straight out of the vendor's Windows updater `.exe` and sends it over USB HID using the same IAP protocol. The protocol was worked out by disassembling that updater. No firmware is included in this repository. You need the vendor `.exe`.

## The story

I'd been happily using my SPM ARA 87 until the Fn key started acting stuck. The keyboard behaved as if Fn were held down even when I wasn't touching it. SPM had released new firmware with a fix, but the only update tools were Windows `.exe` files, and I'm on a Mac.

Rather than borrow a Windows machine, I decided to write my own updater. I opened up the vendor's dongle updater and found the firmware image stored inside the `.exe`. Then I disassembled the tool to work out its USB HID protocol: the 64-byte frames, the header, block and finish commands, and the CRC16 checks. I rebuilt all of it in Python, and the result is `ara87_dongle_update.py`.

Then came the plot twist. The keyboard itself never needed any of this. Turn the power switch off, hold **ESC** while plugging in the cable, and it shows up as a USB drive. Drag the `.bin` onto it and you're done. The Fn bug went away with a simple drag and drop. 🙃

The dongle still has no official way to update from a Mac, so the tool stays here in case it helps someone. A note on how far it's been tested: it reads the firmware correctly, builds every frame, and finds the dongle. My dongle was already on the latest firmware (V0101), though, so a full flash hasn't been run on real hardware yet.

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

### 동글 펌웨어 업데이트 (한국어)

SPM은 2.4G 동글 펌웨어를 Windows용 `.exe`로만 배포합니다. 이 스크립트는 그 `.exe` 안에 들어 있는 펌웨어를 바로 꺼내서 USB로 동글에 씁니다. 파일을 따로 변환할 필요가 없습니다.

1. 준비 (처음 한 번만):
   ```sh
   brew install hidapi
   python3 -m venv venv && venv/bin/pip install hid
   ```
2. SPM 홈페이지에서 받은 동글 업데이터 `.exe`가 정상인지 확인합니다. 이 단계에서는 장치에 아무것도 쓰지 않습니다.
   ```sh
   venv/bin/python ara87_dongle_update.py --exe "(동글)ARA 87_2.4G_V0101_260331.exe" --dry-run
   ```
3. 동글을 Mac에 꽂고 업데이트를 실행합니다.
   ```sh
   DYLD_LIBRARY_PATH=/opt/homebrew/lib venv/bin/python ara87_dongle_update.py --exe "(동글)ARA 87_2.4G_V0101_260331.exe"
   ```
   - 실행하면 현재 동글의 펌웨어 버전(`bcdDevice`, 예: `0x0101` = V0101)이 표시됩니다. 받은 파일과 버전이 같으면 업데이트할 필요가 없습니다.
   - `y`를 입력하면 업데이트가 시작됩니다. `done`이 나올 때까지 동글을 뽑지 마세요.
   - 업데이트가 끝나면 동글이 자동으로 재부팅됩니다.

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
