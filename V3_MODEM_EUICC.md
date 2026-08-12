# v3 modem eUICC notes

The modem bridge now exposes three *transport* PC/SC first-slots, but only two are shown as normal
Dashboard readers:

- `VoWiFi Modem SIM PIN-SWu 00 00` — bridge-owned logical channel for PIN/SWu
- `VoWiFi Modem SIM IMS 00 00` — bridge-owned logical channel for IMS-AKA
- `VoWiFi Modem eUICC LPA 00 00` — hidden management transport on modem basic channel

The LPA transport is not a third physical chip. It is a management view of the same modem-resident
eUICC. lpac needs this path because ISD-R / ES10 operations may create/manage logical channels and
therefore must not be forced onto a bridge-owned logical channel or have MANAGE CHANNEL rejected.

`00 01` readers created by vsmartcard are companion slots and are hidden from normal APIs/UI.

When enabling the modem bridge, install.sh records the modem-authoritative PIN state in
`data/modem-sim-bridge.json` using `AT+CPIN?` and `AT+CLCK="SC",2`. This avoids incorrectly showing
"SIM locked" when the retry-counter APDU returns `63Cx` while PIN facility locking is actually off.
