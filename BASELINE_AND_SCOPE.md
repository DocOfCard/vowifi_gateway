# Baseline and scope

Target upstream interface for this integration is `vhu231/vowifi_gateway` around commit:

`3df37944a8222aca2235bee87c47e6b10f776548`

The downloadable tree is not claimed to be a byte-for-byte GitHub archive of that commit. It is the complete integration tree available in this session, with the vhu231 authentication/config/engine interfaces preserved and the local modem/SOCKS5 work applied on top.

## Reference implementations used

The redesign intentionally cross-checked three implementations:

- `MddIdd/mdd-sim-gateway`: ModemManager command passthrough, `AT+CSIM`, UICC logical-channel allocation, Quectel-style `MANAGE CHANNEL CLOSE` and VPCD framing/lifecycle.
- `MengMengCode/VoCat`: SOCKS5 as a real VoWiFi datagram transport using RFC 1928 UDP ASSOCIATE, including IKE/500, NAT-T/4500, ESP-over-UDP and SOCKS5 control-connection lifetime.
- `vhu231/vowifi_gateway@3df37944...`: existing web authentication, control/engine lifecycle, reader binding, SWu/IMS implementation and UI structure.

The local implementation is adapted rather than copied wholesale. In particular, Ubuntu 22.04 `vsmartcard-vpcd 3.3` behavior observed on the target QDC507 host required a compatibility layout different from MDD's three-reader assumption: PIN keeper shares the SWu reader while IMS remains isolated on a second UICC logical channel.

## Hardware facts incorporated from real QDC507 testing

- ModemManager identifies the device as Quectel/QUALCOMM and permits command passthrough when started with command support.
- `AT+CCID` succeeds.
- `AT+CSIM=10,"0070000001"` allocates logical channels.
- EC25/QDC507 accepts `MANAGE CHANNEL CLOSE` reliably with explicit `Le=00`.
- ModemManager may take roughly 10-20 seconds to recreate the modem after restart.
- Ubuntu's `libifdvpcd.so` is a symlink under `/usr/lib/pcsc/drivers/serial/`.
- Installing `vsmartcard-vpcd` can reintroduce distro pcscd 1.9.x; the project engine is pinned to pcsc-lite 2.3.3, so the installer now restores the pin automatically.
- systemd's distro pcscd uses `--auto-exit`; the modem bridge requires pcscd/VPCD listeners to stay resident.
