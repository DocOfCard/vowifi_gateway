#!/usr/bin/env python3
"""Bridge a modem-resident UICC to PC/SC through vsmartcard VPCD.

This bridge is tuned for Quectel EC25 / BAIWANG QDC507-class modems managed by
ModemManager. It deliberately leaves tty ownership with ModemManager and sends APDUs
through ``mmcli --command=AT+CSIM=...``.

Compatibility layout (default):
  - logical channel A -> VPCD port 35963 -> shared PIN keeper + SWu/EAP-AKA reader
  - logical channel B -> VPCD port 35965 -> IMS-AKA reader

Why two channels instead of three? Ubuntu's vsmartcard 3.3 exposes two PC/SC slots per
VPCD reader instance and is unreliable when several independent instances are stacked.
The gateway's pin_keeper verifies CHV1 once and then holds an idle connection; it does
not issue ongoing SELECT/APDU traffic, so sharing the SWu reader preserves the important
isolation boundary: SWu and IMS still have independent UICC file-selection state.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

CSIM_RE = re.compile(r'\+CSIM:\s*(\d+)\s*,\s*"([0-9A-Fa-f]*)"')
# Valid TCK (ED). This ATR is only the VPCD presentation layer; actual APDUs are handled
# by the modem-resident UICC through AT+CSIM.
DEFAULT_ATR = bytes.fromhex('3B9F95801FC78031E073FE211B66D0017797020C00ED')
DEFAULT_PORTS = (35963, 35965, 35967)
DEFAULT_ROLES = ('pin+swu', 'ims', 'lpa')


class BridgeError(RuntimeError):
    pass


class MMCard:
    def __init__(self, modem: str, timeout: float = 12.0, debug: bool = False):
        self.modem = str(modem)
        self.timeout = timeout
        self.debug = debug
        self.lock = threading.RLock()
        self.at('AT')

    def at(self, cmd: str) -> str:
        with self.lock:
            try:
                p = subprocess.run(
                    ['mmcli', '-m', self.modem, '--command=' + cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise BridgeError(f'mmcli failed: {exc}') from exc
            out = p.stdout or ''
            if p.returncode:
                raise BridgeError(out.strip() or f'mmcli exit {p.returncode}')
            return out

    def csim(self, apdu: bytes) -> bytes:
        hx = apdu.hex().upper()
        if self.debug:
            print(f'[bridge] APDU -> {hx}', flush=True)
        out = self.at(f'AT+CSIM={len(hx)},"{hx}"')
        m = CSIM_RE.search(out)
        if not m:
            raise BridgeError('missing +CSIM response: ' + out.strip()[-300:])
        data = bytes.fromhex(m.group(2))
        if self.debug:
            sw = data[-2:].hex().upper() if len(data) >= 2 else '?'
            print(f'[bridge] APDU <- {len(data)} bytes sw={sw}', flush=True)
        return data

    def open_channel(self) -> int:
        r = self.csim(bytes.fromhex('0070000001'))
        if len(r) != 3 or r[-2:] != b'\x90\x00':
            raise BridgeError('MANAGE CHANNEL OPEN failed: ' + r.hex().upper())
        ch = int(r[0])
        if not 1 <= ch <= 19:
            self.close_channel(ch)
            raise BridgeError(f'unsupported logical channel {ch}; expected 1..19')
        return ch

    def close_channel(self, ch: int) -> bool:
        try:
            # EC25/QDC507 firmware accepts CLOSE reliably when Le=00 is explicit.
            r = self.csim(bytes((0x00, 0x70, 0x80, ch & 0xFF, 0x00)))
        except Exception as exc:
            print(f'[bridge] close channel {ch} error: {exc}', flush=True)
            return False
        ok = len(r) >= 2 and r[-2:] == b'\x90\x00'
        if ok:
            print(f'[bridge] closed channel {ch}', flush=True)
        else:
            print(f'[bridge] close channel {ch} failed: {r.hex().upper()}', flush=True)
        return ok

    @staticmethod
    def on_channel(apdu: bytes, ch: int):
        if len(apdu) < 2:
            return None, bytes.fromhex('6700')
        if apdu[0] == 0xFF:
            return None, bytes.fromhex('6D00')
        if apdu[1] == 0x70:  # clients must not manage bridge-owned channels
            return None, bytes.fromhex('6881')
        if apdu[0] == 0xA0:  # legacy GSM class has no logical-channel coding
            return None, bytes.fromhex('6881')
        if not 1 <= ch <= 19:
            return None, bytes.fromhex('6881')

        cla = apdu[0]
        if ch <= 3:
            new_cla = (cla & 0xFC) | ch
        else:
            # ISO/IEC 7816-4 further-interindustry logical channel coding (4..19).
            new_cla = (cla & 0x80) | 0x40 | (ch - 4)
        return bytes((new_cla,)) + apdu[1:], None

    def transmit(self, apdu: bytes, ch: int, *, passthrough: bool = False) -> bytes:
        if passthrough:
            # Dedicated eUICC/LPA path: send the PC/SC APDU unchanged on the modem's
            # basic channel. lpac/libeuicc must be allowed to SELECT ISD-R and issue
            # MANAGE CHANNEL itself, exactly as direct modem LPA implementations do.
            rewritten, local = apdu, None
        else:
            rewritten, local = self.on_channel(apdu, ch)
        if local is not None:
            return local
        try:
            return self.csim(rewritten)
        except Exception as exc:
            print(f'[bridge] channel {ch} modem error: {exc}', flush=True)
            return bytes.fromhex('6F00')

    def reset_slot(self, ch: int) -> None:
        apdu, local = self.on_channel(bytes.fromhex('00A40004023F00'), ch)
        if local is not None:
            return
        try:
            self.csim(apdu)
        except Exception as exc:
            print(f'[bridge] channel {ch} reset/select MF failed: {exc}', flush=True)


def recv_exact(sock: socket.socket, n: int):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def write_state(path: Path, channels: list[int], ports: list[int], status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps({
        'version': 2,
        'channels': channels,
        'ports': ports,
        'status': status,
        'updated_at': int(time.time()),
    }, sort_keys=True) + '\n', encoding='utf-8')
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def cleanup_previous_state(card: MMCard, path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        channels = [int(x) for x in data.get('channels', [])]
    except (OSError, ValueError, TypeError):
        return
    if channels:
        print(f'[bridge] cleaning recorded channels from prior run: {channels}', flush=True)
    for ch in channels:
        if 1 <= ch <= 19:
            card.close_channel(ch)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def slot_worker(card: MMCard, host: str, port: int, role: str, ch: int,
                atr: bytes, stop: threading.Event, debug: bool,
                passthrough: bool = False) -> None:
    while not stop.is_set():
        sock = None
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.settimeout(None)
            print(f'[bridge] role={role} connected {host}:{port} channel={ch}', flush=True)
            while not stop.is_set():
                header = recv_exact(sock, 2)
                if header is None:
                    break
                (length,) = struct.unpack('>H', header)
                if length == 0:
                    continue
                payload = recv_exact(sock, length)
                if payload is None:
                    break
                if length == 1:
                    ctl = payload[0]
                    if debug:
                        print(f'[bridge] role={role} control=0x{ctl:02X} channel={ch}', flush=True)
                    if ctl == 0x04:  # GET ATR
                        sock.sendall(struct.pack('>H', len(atr)) + atr)
                    elif ctl == 0x00:  # POWER OFF; keep bridge-owned UICC channel open
                        pass
                    elif ctl in (0x01, 0x02):  # POWER ON / RESET
                        # Do not rewrite/select MF on the dedicated LPA basic-channel path;
                        # lpac/libeuicc owns that session state.
                        if not passthrough:
                            card.reset_slot(ch)
                    continue
                response = card.transmit(payload, ch, passthrough=passthrough)
                sock.sendall(struct.pack('>H', len(response)) + response)
        except (OSError, ConnectionError) as exc:
            if not stop.is_set():
                print(f'[bridge] role={role} disconnected: {exc}', flush=True)
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        stop.wait(1.0)


def parse_ports(value: str) -> list[int]:
    try:
        ports = [int(x.strip()) for x in value.split(',') if x.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError('ports must be comma-separated integers') from exc
    if len(ports) != 3 or any(p < 1 or p > 65535 for p in ports):
        raise argparse.ArgumentTypeError('exactly three TCP ports are required')
    return ports


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--modem', required=True, help='ModemManager modem index, e.g. 0')
    ap.add_argument('--vpcd-host', default='127.0.0.1')
    ap.add_argument('--vpcd-ports', type=parse_ports,
                    default=list(DEFAULT_PORTS), help='three VPCD ports, default 35963,35965,35967')
    # Backward-compatible CLI accepted by earlier package; base-port now means the first
    # of two spaced VPCD instances (base and base+2).
    ap.add_argument('--vpcd-base-port', type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument('--slots', type=int, default=2, choices=(2,), help=argparse.SUPPRESS)
    ap.add_argument('--state-file', default='/run/vowifi-modem-sim-bridge/state.json')
    ap.add_argument('--atr', default=DEFAULT_ATR.hex())
    ap.add_argument('--debug', action='store_true')
    args = ap.parse_args()

    ports = args.vpcd_ports
    if args.vpcd_base_port is not None:
        ports = [args.vpcd_base_port, args.vpcd_base_port + 2, args.vpcd_base_port + 4]

    card = MMCard(args.modem, debug=args.debug)
    state_path = Path(args.state_file)
    cleanup_previous_state(card, state_path)

    channels: list[int] = []
    try:
        for _ in range(2):
            ch = card.open_channel()
            if ch in channels:
                raise BridgeError(f'duplicate logical channel {ch}')
            channels.append(ch)
            write_state(state_path, channels, ports, 'allocating')
        write_state(state_path, channels, ports, 'ready')
        print(f'[bridge] allocated logical channels: {channels[0]} (PIN+SWu), {channels[1]} (IMS); LPA uses basic channel passthrough', flush=True)
    except Exception:
        for ch in channels:
            card.close_channel(ch)
        try:
            state_path.unlink()
        except FileNotFoundError:
            pass
        raise

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    atr = bytes.fromhex(args.atr)
    threads = []
    workers = [
        (DEFAULT_ROLES[0], ports[0], channels[0], False),
        (DEFAULT_ROLES[1], ports[1], channels[1], False),
        # eUICC management path: no bridge-owned logical channel. APDUs are passed
        # through unchanged on the modem basic channel so lpac can manage ISD-R itself.
        (DEFAULT_ROLES[2], ports[2], 0, True),
    ]
    for role, port, ch, passthrough in workers:
        t = threading.Thread(
            target=slot_worker,
            args=(card, args.vpcd_host, port, role, ch, atr, stop, args.debug, passthrough),
            daemon=True,
        )
        t.start()
        threads.append(t)

    try:
        while not stop.wait(1.0):
            if not all(t.is_alive() for t in threads):
                raise BridgeError('a VPCD bridge worker exited unexpectedly')
    finally:
        write_state(state_path, channels, ports, 'stopping')
        for ch in channels:
            card.close_channel(ch)
        try:
            state_path.unlink()
        except FileNotFoundError:
            pass
        print('[bridge] channels closed', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
