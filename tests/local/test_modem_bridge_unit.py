#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'host' / 'modem_sim_bridge.py'
spec = importlib.util.spec_from_file_location('modem_sim_bridge', PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def main():
    expected = {1: 0x01, 2: 0x02, 3: 0x03, 4: 0x40, 5: 0x41, 19: 0x4F}
    for ch, cla in expected.items():
        rewritten, local = bridge.MMCard.on_channel(bytes.fromhex('00A40004023F00'), ch)
        assert local is None
        assert rewritten[0] == cla, (ch, rewritten.hex())

    for ch, cla in {4: 0xC0, 19: 0xCF}.items():
        rewritten, local = bridge.MMCard.on_channel(bytes.fromhex('80CA000000'), ch)
        assert local is None
        assert rewritten[0] == cla, (ch, rewritten.hex())

    assert bridge.MMCard.on_channel(bytes.fromhex('0070000001'), 1)[1] == bytes.fromhex('6881')
    assert bridge.DEFAULT_ATR[-1] == 0xED
    assert bridge.parse_ports('35963,35965,35967') == [35963, 35965, 35967]
    print('modem bridge unit tests: OK')


if __name__ == '__main__':
    main()
