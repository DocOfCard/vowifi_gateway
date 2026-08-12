# VoWiFi Gateway 本地增强版：模块内 SIM + SOCKS5 ePDG 代理

## 1. 目标

本增强版围绕两个实际部署需求：

1. **SIM 不拔出蜂窝模块**：支持 BAIWANG/QDC507、Quectel EC25 以及其它被 ModemManager 管理、且支持 `AT+CSIM` + ISO 7816 `MANAGE CHANNEL` 的模块内 UICC。
2. **VoWiFi 经 SOCKS5 出口**：像 VoCat 一样，让 IKEv2 / NAT-T / userspace ESP 真正通过 SOCKS5 `UDP ASSOCIATE` 出口，而不是使用只对 HTTP/TCP 有效的 `HTTP_PROXY`。

登录认证保持项目现有控制面认证功能；本次改造不要求为代理或 modem bridge 改写认证逻辑。

---

## 2. 模块内 SIM 的实现

### 2.1 设计取舍：两个 logical channel，而不是强行三个 VPCD reader

MDD 的核心思路是正确的：模块 SIM 通过 `AT+CSIM`，并用 UICC logical channel 隔离不同认证消费者。实际在 Ubuntu 22.04 的 `vsmartcard-vpcd 3.3` 上验证后，本增强版做了一个兼容性调整：

- `pin_keeper.py` 与 `swu_ike.py` **共享一个 PC/SC reader / logical channel**；
- `ami_usim.py` 使用第二个独立 reader / logical channel。

这是安全的，因为 `pin_keeper` 在验证 CHV1 后只保持空闲连接，不再持续执行 SELECT/APDU；真正会改变 UICC file-selection state 的 SWu 与 IMS 仍被隔离。这样避免依赖 vsmartcard 3.3 对多实例/双 slot 的不稳定枚举行为。

```text
QDC507 / EC25
    |
    | ModemManager mmcli --command="AT+CSIM=..."
    v
host/modem_sim_bridge.py
    |
    +-- logical channel A --> VPCD instance A / 35963 --> reader 0 --> PIN keeper + SWu
    +-- logical channel B --> VPCD instance B / 35965 --> reader 2 --> IMS-AKA
```

每个 vsmartcard VPCD instance 还会自动枚举一个 companion slot，所以 `pcsc_scan` 通常会看到 4 个 reader；reader 1/3 显示 `Card removed` 是预期状态，不使用它们。

### 2.2 QDC507 / EC25 logical channel 处理

bridge 使用 `MANAGE CHANNEL OPEN` 动态接受 ISO 7816 logical channel 1..19，不再假定一定是 1/2/3。channel 4..19 使用正确的扩展 CLA 编码。

关闭 channel 使用带 `Le=00` 的 APDU：

```text
00 70 80 <channel> 00
```

这是为了兼容部分 Quectel/BAIWANG 固件对裸 Case-1 `MANAGE CHANNEL CLOSE` 返回 AT ERROR 的行为。

bridge 将自己分配的 channel 写入 `/run/vowifi-modem-sim-bridge/state.json`。异常重启时只回收自己上一轮记录的 channel；正常 SIGTERM 时逐个 CLOSE 并记录失败，不再静默吞掉 channel 泄漏。

### 2.3 ModemManager 而非直接抢 ttyUSB

bridge 不直接打开 `/dev/ttyUSB*`。所有 AT 命令通过：

```bash
mmcli -m 0 --command='AT+CSIM=...'
```

安装器会启用 ModemManager command interface，然后循环等待指定 modem 真正重新枚举并能执行 `AT`，不再使用固定 3 秒等待。EC25/QDC507 实测可能需要十几秒。

### 2.4 PC/SC / VPCD 安装器修正

`modem-bridge` 子命令现在会自动处理实际部署中发现的几个坑：

- `libifdvpcd.so` 在 Ubuntu 是 symlink，不再用 `find -type f` 漏掉；
- 安装 `vsmartcard-vpcd` 若把 host pcscd 拉回 1.9.x，会自动重新执行项目的 PC/SC pinning，恢复与 engine 一致的 2.3.3；
- 备份 distro 默认 `/etc/reader.conf.d/vpcd`，避免重复 Virtual PCD；
- 给 pcscd 加常驻 drop-in，去掉 `--auto-exit`，防止 35963/35965 listener 空闲后消失；
- 启动 bridge 前检查 VPCD listener 已经存在。

### 2.5 engine reader 映射

modem bridge 默认映射为：

```yaml
reader_mode: modem_bridge
reader_pin_index: 0
reader_swu_index: 0
reader_ims_index: 2
```

engine 启动后：

```text
pin_keeper -> reader 0
swu_ike    -> reader 0
ami_usim   -> reader 2
```

旧增强版如果保存过 `0/1/2`，控制面会一次性迁移为 `0/0/2` 并写入 `reader_bridge_layout=compat-v2`。之后用户手工修改的 index 会被保留。

普通 USB CCID reader 使用 `reader_mode=single`，旧行为不变。

---

## 3. SOCKS5 实现

### 3.1 不是 HTTP_PROXY

IKE/ESP 是 UDP。设置：

```text
HTTP_PROXY=http://...
HTTPS_PROXY=http://...
```

不能代理 ePDG 的 UDP/500、UDP/4500。

本版直接在 `engine/swu_ike.py` 的 ePDG-facing UDP socket 层使用 PySocks：

```text
SOCKS5 TCP control connection
        |
        +-- RFC 1928 UDP ASSOCIATE
               |
               +-- ePDG UDP/500   IKE_SA_INIT
               +-- ePDG UDP/4500  IKE_AUTH + NAT-T ESP + keepalive
```

engine 镜像原本已经安装 `python3-pysocks`，无需新增 Python 包。

### 3.2 为什么代理模式强制 NAT-T

SOCKS5 UDP 无法传输 raw IP protocol 50 ESP。因此代理开启后：

- 初始 IKE_SA_INIT 仍发送到 ePDG UDP/500；
- SA_INIT 后强制 `userplane_mode=NAT_TRAVERSAL`；
- IKE_AUTH、后续 INFORMATIONAL/CREATE_CHILD_SA 以及 userspace ESP 全部走 UDP/4500；
- idle NAT keepalive `0xFF` 也走同一个 SOCKS5 UDP 模式。

直连模式完全保留原有 raw ESP / NAT-T 自动判断行为。

### 3.3 每线路代理配置

WebUI → SIM Config 新增：

```text
SOCKS5 ePDG proxy
  ePDG transport: Direct / SOCKS5
  Server
  Port
  Username
  Password
  Resolve destination names through SOCKS5
```

配置保存在该 line 下；不同 SIM 可走不同代理。

示例：

```text
Mode: SOCKS5
Server: 10.10.100.253
Port: 7890
Username: 空
Password: 空
Remote DNS: 按你的 Nikki 配置选择
```

密码字段在编辑页面留空时保留原值，不会因为保存其它设置而清空。

---

## 4. 安装与启用模块 SIM

先确认模块：

```bash
sudo mmcli -L
sudo mmcli -m 0
```

如果以前手工测试开过 logical channel，例如：

```text
+CSIM: 6,"029000"
```

应先关闭 channel 2：

```bash
sudo mmcli -m 0 --command='AT+CSIM=10,"0070800200"'
```

然后：

```bash
cd ~/vowifi_gateway
sudo ./install.sh modem-bridge 0
```

检查：

```bash
systemctl status vowifi-modem-sim-bridge --no-pager
journalctl -u vowifi-modem-sim-bridge -n 100 --no-pager
pcsc_scan
```

目标通常会看到四个 reader：

```text
0: VoWiFi Modem SIM PIN-SWu 00 00   <- 使用
1: VoWiFi Modem SIM PIN-SWu 00 01   <- companion slot，不使用
2: VoWiFi Modem SIM IMS 00 00       <- 使用
3: VoWiFi Modem SIM IMS 00 01       <- companion slot，不使用
```

启用 bridge 后 reader 0 和 reader 2 应显示 `Card inserted`。WebUI 选择 `Modem internal SIM`，推荐保持 PIN=0、SWu=0、IMS=2。

---

## 5. Docker 模式重新构建

因为修改了 `swu_ike.py`、`entrypoint.sh`、`render.py` 和 WebUI，需要重建 engine + control：

```bash
cd ~/vowifi_gateway
sudo ./install.sh reload --mode docker --engines
```

如果旧安装脚本已经记住 docker mode，通常也可：

```bash
sudo ./install.sh reload --engines
```

数据目录不会因为 reload 被清空。

---

## 6. SOCKS5 验证

开启某 line 的 SOCKS5 后重启该 line，查看 IKE 日志，应出现：

```text
SOCKS5 UDP proxy enabled: 10.10.100.253:7890 ...
SOCKS5 UDP socket ready for IKE/500 ...
SOCKS5 UDP socket ready for NAT-T/4500 ...
SOCKS5 forces RFC3948 NAT-T: IKE/ESP continue on UDP/4500
```

在 Nikki 路由器抓包时，应看到代理设备与 SOCKS5 上游之间的流量，而不应再看到 engine 所在 Ubuntu 直接对 ePDG 建 UDP/500/4500 会话。

---

## 7. 故障排查

### `mmcli --command` Unauthorized

说明 ModemManager 没有以 debug command interface 运行。重新执行：

```bash
sudo ./install.sh modem-bridge 0
```

### `MANAGE CHANNEL OPEN failed`

可能是：

- 模块不支持 `AT+CSIM`；
- UICC 不支持足够的 logical channel；
- 之前测试泄漏了 channel；
- SIM/模块需要 reset。

先查看：

```bash
sudo mmcli -m 0 --command='AT+CSIM=10,"0070000001"'
```

### 三个 VPCD reader 只出现一个/两个

检查：

```bash
cat /etc/reader.conf.d/vowifi-modem-vpcd.conf
find /usr/lib /usr/local/lib -name libifdvpcd.so
journalctl -u pcscd -n 100 --no-pager
```

### SOCKS5 TCP 能用但 VoWiFi 不通

必须确认 SOCKS5 server 真正支持 **UDP ASSOCIATE**。很多所谓 SOCKS5 入口只支持 CONNECT/TCP；这种情况下网页/curl 能代理，但 IKE UDP 一定失败。

### IKE/500 通但 4500 不通

检查代理上游、Nikki relay、VLESS/SS relay 是否允许 SOCKS5 UDP。代理模式依赖 4500，因为 ESP 被封装在 NAT-T UDP/4500。

---

## 8. 安全说明

- SOCKS5 用户名/密码不会写进 IKE 日志，但会随 line 配置保存在本地运行数据中；保护 `data/` 权限和备份。
- ModemManager debug mode 是为了开放 `mmcli --command` 接口；因此不要给不可信本地用户任意 `mmcli`/D-Bus 权限。
- WebUI 不应直接暴露到公网；启用项目提供的登录密码，并结合防火墙/WG/VPN 使用。
- `/var/run/docker.sock` 等价于高权限宿主控制能力；docker control-plane 模式尤其应只在可信网络使用。

---

## 9. 回滚

关闭模块 bridge：

```bash
sudo ./install.sh modem-bridge-disable
```

这会停止 bridge、删除 ModemManager command-interface drop-in、删除本增强版创建的 VPCD reader 配置，并重启相关服务。

SOCKS5 回滚只需在 SIM Config 选择 `Direct`，保存并重启 line。
