#!/usr/bin/env python3
"""ARA 87 2.4G dongle firmware updater for macOS.

Re-implements the USB-HID IAP protocol used by the vendor's Windows updater
("(동글)ARA 87_2.4G_V0101_260331.exe", Ingchips ING91680C). The firmware image
is taken straight out of the .exe overlay, so no file conversion is needed.

Protocol (reverse engineered from the .exe):
  HID frame (64 B, output & input, report ID from config = 0x3F, usage page 0xFF00)
    [0] report id  [1] 0xAA  [2] 0x00
    [3..4] u16 LE: bits0-14 = packets remaining after this one, bit15 = first packet
    [5..6] u16 LE: data length n (<= 56)
    [7..7+n) data   [7+n] XOR of bytes [2 .. 7+n)
  Message (split over frames):  cmd, u16 LE len, payload, CRC16/MODBUS (big endian)
    A0  header   : 128-byte IAP header
    A1  block    : u16 block# (0xFFFF for last) + u32 offset + block data
    A4  finish   : u16 reboot delay (ms)
  Reply message: B0, status, .., u16 len @3, payload, CRC16 (status 0 == OK)

Usage:
  pip install hid    (needs `brew install hidapi`)
  python3 ara87_dongle_update.py --exe "<path to .exe>" [--dry-run] [--yes]
"""
import argparse
import struct
import sys
import time

MAGIC = 0x5F2C6AAC
FRAME = 64
CHUNK = 56

STATUS = {
    0x00: "success", 0xE0: "invalid cmd", 0xE1: "length error", 0xE2: "CRC error",
    0xE3: "block number error", 0xE4: "block size error", 0xE5: "write offset error",
    0xE6: "read offset error", 0xE7: "parameter error", 0xE8: "flash operation failed",
    0xE9: "condition not satisfied", 0xF0: "header: upgradeFlag", 0xF1: "header: chipID",
    0xF2: "header: itemInfo", 0xF3: "header: HW version", 0xF4: "header: SW version",
    0xF5: "header: CHECK INFO", 0xF6: "header: BLOCK INFO", 0xF7: "header: upgrade type",
    0xF8: "header: encrypt", 0xF9: "header: headerCRC", 0xFA: "header: load address",
    0xFB: "header: bin size",
}


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def xor8(data: bytes) -> int:
    x = 0
    for b in data:
        x ^= b
    return x


def extract_from_exe(path):
    d = open(path, "rb").read()
    if struct.unpack_from("<I", d, len(d) - 4)[0] != MAGIC:
        sys.exit("overlay magic not found - not a supported updater .exe")
    cfg = struct.unpack_from("<I", d, len(d) - 8)[0]
    fw_off, fw_size, ndev, dev_off = struct.unpack_from("<IIII", d, cfg)
    retry, reboot_delay, switch_delay, search_to, ack_to = struct.unpack_from("<5I", d, cfg + 0x20)
    devs = [struct.unpack_from("<HHB", d, dev_off + 5 * i) for i in range(ndev)]
    return dict(fw=d[fw_off:fw_off + fw_size], devs=devs, retry=retry,
                switch_delay=switch_delay, ack_timeout=ack_to, search_timeout=search_to)


def parse_header(fw):
    h = fw[:0x80]
    if h[:8] != b"INGCHIPS":
        sys.exit("payload has no INGCHIPS header")
    s = lambda o: h[o + 1:o + 1 + h[o]].decode(errors="replace")
    info = dict(chip=s(8), item=s(0x18), hw=h[0x30:0x36].decode(), sw=h[0x36:0x3C].decode(),
                block=struct.unpack_from("<H", h, 0x42)[0],
                nblocks=struct.unpack_from("<I", h, 0x44)[0],
                load=struct.unpack_from("<I", h, 0x6A)[0],
                size=struct.unpack_from("<I", h, 0x6E)[0])
    body = fw[0x80:]
    if info["size"] != len(body):
        sys.exit(f"bin size mismatch: header {info['size']} vs payload {len(body)}")
    if -(-len(body) // info["block"]) != info["nblocks"]:
        sys.exit("block count mismatch")
    return info, body


def message(cmd, payload):
    m = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
    return m + struct.pack(">H", crc16_modbus(m))


def frames(msg, rid):
    chunks = [msg[i:i + CHUNK] for i in range(0, len(msg), CHUNK)]
    for i, c in enumerate(chunks):
        ctl = ((len(chunks) - 1 - i) & 0x7FFF) | (0x8000 if i == 0 else 0)
        f = bytes([rid, 0xAA, 0x00]) + struct.pack("<HH", ctl, len(c)) + c
        f += bytes([xor8(f[2:])])
        yield f.ljust(FRAME, b"\0")


class Link:
    def __init__(self, dev, rid, timeout_ms, dry):
        self.dev, self.rid, self.to, self.dry = dev, rid, timeout_ms, dry

    def transact(self, msg, label):
        last = None
        for f in frames(msg, self.rid):
            if self.dry:
                continue
            if self.dev.write(f) < 0:
                raise IOError(f"{label}: hid write failed")
            r = bytes(self.dev.read(FRAME, self.to))
            if not r:
                raise IOError(f"{label}: no reply within {self.to} ms")
            last = r
        if self.dry:
            return 0
        return self.parse_reply(last, label)

    def parse_reply(self, r, label):
        # tolerate replies delivered with or without the report-id byte
        if r[0] != 0xAA and len(r) > 1 and r[1] == 0xAA:
            r = r[1:]
        if r[0] != 0xAA:
            raise IOError(f"{label}: bad reply frame {r[:16].hex()}")
        n = struct.unpack_from("<H", r, 4)[0]
        if xor8(r[1:6 + n]) != r[6 + n]:
            raise IOError(f"{label}: reply XOR error {r[:16].hex()}")
        m = r[6:6 + n]
        if m[0] != 0xB0:
            raise IOError(f"{label}: unexpected reply {m.hex()}")
        plen = struct.unpack_from("<H", m, 3)[0]
        if len(m) >= plen + 7 and struct.unpack_from(">H", m, plen + 5)[0] != crc16_modbus(m[:plen + 5]):
            raise IOError(f"{label}: reply CRC error {m.hex()}")
        return m[1]


def find_device(hid, devs, timeout_s):
    end = time.time() + timeout_s
    while True:
        for vid, pid, rid in devs:
            for d in hid.enumerate(vid, pid):
                if d["usage_page"] == 0xFF00:
                    return d, rid
        if time.time() > end:
            sys.exit("dongle not found (VID/PID %s, usage page 0xFF00)" %
                     ", ".join(f"{v:04X}:{p:04X}" for v, p, _ in devs))
        time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True, help="vendor Windows updater .exe")
    ap.add_argument("--dry-run", action="store_true", help="build all frames, touch no hardware")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = ap.parse_args()

    cfg = extract_from_exe(a.exe)
    info, body = parse_header(cfg["fw"])
    print(f"image : chip={info['chip']} item={info['item']} hw={info['hw']} sw={info['sw']}")
    print(f"        load=0x{info['load']:08X} size={info['size']} blocks={info['nblocks']}x{info['block']}")
    print("target: " + ", ".join(f"{v:04X}:{p:04X} rid=0x{r:02X}" for v, p, r in cfg["devs"]))

    dev = None
    rid = cfg["devs"][0][2]
    if not a.dry_run:
        import hid
        d, rid = find_device(hid, cfg["devs"], cfg["search_timeout"] / 1000)
        print(f"found : {d['product_string']} fw bcdDevice=0x{d['release_number']:04X}")
        if not a.yes and input("Flash dongle now? Keep it plugged in until done. [y/N] ").lower() != "y":
            sys.exit("aborted")
        dev = hid.device()
        dev.open_path(d["path"])

    link = Link(dev, rid, cfg["ack_timeout"], a.dry_run)
    bs = info["block"]

    def step(msg, label):
        for attempt in range(max(1, cfg["retry"])):
            try:
                st = link.transact(msg, label)
                break
            except IOError as e:
                if attempt + 1 >= max(1, cfg["retry"]):
                    raise
                print(f"\n  retry ({e})")
        if st != 0:
            raise SystemExit(f"\n{label}: device reported 0x{st:02X} {STATUS.get(st, 'unknown error')}")

    step(message(0xA0, cfg["fw"][:0x80]), "header")
    for i in range(info["nblocks"]):
        last = i == info["nblocks"] - 1
        blk = body[i * bs:(i + 1) * bs]
        num = 0xFFFF if last else i
        step(message(0xA1, struct.pack("<HI", num, i * bs) + blk), f"block {i}")
        print(f"\r  writing {i + 1}/{info['nblocks']}", end="", flush=True)
    print()
    step(message(0xA4, struct.pack("<H", cfg["switch_delay"] & 0xFFFF)), "finish")
    if dev:
        dev.close()
        time.sleep((cfg["switch_delay"] + 200) / 1000)
    print("dry run OK - all frames built" if a.dry_run else "done - dongle is rebooting into the new firmware")


if __name__ == "__main__":
    main()
