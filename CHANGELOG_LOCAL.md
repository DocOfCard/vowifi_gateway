# Local integration changelog

## 2026-08-11 — QDC507/EC25 bridge v2 + SOCKS5 UDP egress

### Modem-resident SIM

- Added ModemManager-backed `AT+CSIM` bridge for BAIWANG QDC507, Quectel EC25 and compatible modems.
- Bridge no longer opens `/dev/ttyUSB*`; ModemManager remains the tty owner.
- Logical channels are allocated dynamically and support ISO 7816 channel numbers 1..19, including extended CLA encoding for channels 4..19.
- Quectel/QDC `MANAGE CHANNEL CLOSE` uses explicit `Le=00`.
- Channel cleanup is no longer silent. The bridge records owned channels in `/run/vowifi-modem-sim-bridge/state.json`, cleans only its own stale state after a crash, and logs CLOSE failures.
- Reworked Ubuntu vsmartcard layout after hardware testing: two stable VPCD instances are used instead of three independent VPCD readers. PIN keeper shares the SWu reader; IMS keeps its own logical channel. Default reader mapping is PIN=0, SWu=0, IMS=2.
- Corrected the presentation ATR TCK (`...00ED`).
- Added complete VPCD control handling for POWER OFF, POWER ON, RESET and GET ATR.

### Installer hardening

- `libifdvpcd.so` symlinks are now accepted (Ubuntu 22.04 path: `/usr/lib/pcsc/drivers/serial/libifdvpcd.so`).
- `modem-bridge` re-pins host pcsc-lite to the project `PCSC_VERSION` after Ubuntu installs `vsmartcard-vpcd` and may pull distro pcscd back in.
- Added persistent pcscd systemd override; VPCD listeners no longer disappear because of `--auto-exit`.
- Default distro VPCD reader config is backed up while the modem bridge is enabled and restored by `modem-bridge-disable`.
- ModemManager restart now waits up to 40 seconds for the requested modem and AT command interface instead of assuming a fixed delay.
- Bridge startup waits for VPCD TCP listeners before allocating UICC channels.
- `modem-bridge-disable` removes all bridge-specific systemd/reader overrides and restores the previous VPCD config.

### Engine integration

- Added `reader_mode=modem_bridge`.
- PIN and SWu default to reader 0; IMS defaults to reader 2.
- Previous experimental `0/1/2` modem mapping is migrated once to `0/0/2`.
- Normal CCID/PCSC reader mode is unchanged.

### SOCKS5 / VoWiFi transport

- Added per-line SOCKS5 configuration to the WebUI/control model.
- Added RFC 1928 UDP ASSOCIATE transport to `swu_ike.py` using PySocks.
- Proxy mode forces RFC 3948 NAT-T: IKE starts on UDP/500 and IKE/ESP continue on UDP/4500.
- SOCKS5 username/password and remote-DNS options are supported.
- Direct mode retains the upstream transport behavior.

### Authentication

- Existing authentication from the vhu231-based control-plane integration is preserved; this local patch does not replace it.

## v3 — modem eUICC management + PIN truth + hidden transport readers

- Added a third VPCD transport (`35967`) named `VoWiFi Modem eUICC LPA` for eUICC management.
  Unlike the VoWiFi PIN/SWu and IMS readers, this transport uses the modem basic channel and
  passes APDUs through unchanged, including MANAGE CHANNEL, so lpac/libeuicc can manage ISD-R.
- `lpa.py` automatically redirects eSIM operations selected on `VoWiFi Modem SIM ...` readers
  to the hidden LPA transport while keeping the user-facing physical-reader selection unchanged.
- Modem PIN state now uses the authoritative `AT+CPIN?` + `AT+CLCK="SC",2` snapshot instead of
  treating a `63Cx` retry-counter probe as proof that PIN is enabled.
- Dashboard/API hide vsmartcard `00 01` companion slots and the internal LPA transport, so
  transport artifacts no longer appear as extra physical chips.
- STANDALONE lpac subprocesses now receive `$VOWIFI_DATA/lpac/lib` in `LD_LIBRARY_PATH`, fixing
  dlopened driver dependencies without host-side patchelf.
- Control image now includes libcurl runtime and registers `/usr/lib64` with ldconfig for the
  source-built pcsc-lite client library.
