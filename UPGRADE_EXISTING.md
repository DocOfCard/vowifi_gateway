# 从已安装的 vowifi_gateway 升级

如果宿主已经安装并运行过原版/上一版增强版，不要删除 `data/`，也不要删除 Docker 镜像。

## 1. 覆盖源码但保留 data 和 .git

在解压后的增强版目录执行：

```bash
./upgrade-existing.sh ~/vowifi_gateway
```

脚本会在目标目录先创建一个仅包含本地改动关键文件的 tar.gz 备份，然后使用 rsync 覆盖源码；`data/`、`.git/`、本地 venv/node_modules 不会被覆盖。

## 2. 重建应用

如果从原版升级，需要重新构建 engine/control，以包含 SOCKS5、reader mapping 和 WebUI：

```bash
cd ~/vowifi_gateway
sudo ./install.sh reload --mode docker --engines
```

如果你已经运行的是上一版包含 SOCKS5 的增强包，只改 modem bridge 时可先不重建 engine，直接启用 bridge；但最终仍建议在维护窗口执行一次 reload，让 WebUI/config migration 与源码完全一致。

## 3. 启用模块内 SIM

先停用会操作同一张 SIM 的 VoCat：

```bash
sudo docker stop vocat
```

然后：

```bash
cd ~/vowifi_gateway
sudo ./install.sh modem-bridge 0
```

安装器会自动：

- 安装/确认 vsmartcard-vpcd；
- 恢复 host pcsc-lite 到项目固定版本 2.3.3（若 Ubuntu 包把它降到 1.9.x）；
- 备份 distro 默认 VPCD reader；
- 让 pcscd 常驻，避免 `--auto-exit` 关闭 35963/35965；
- 启用 ModemManager command interface；
- 等待 modem 重新枚举；
- 创建两个 logical channel；
- 建立 PIN+SWu 与 IMS 两路 VPCD bridge。

## 4. 正常结果

```bash
pcsc_scan
```

通常看到：

```text
0: VoWiFi Modem SIM PIN-SWu 00 00   Card inserted
1: VoWiFi Modem SIM PIN-SWu 00 01   Card removed   # unused companion slot
2: VoWiFi Modem SIM IMS 00 00       Card inserted
3: VoWiFi Modem SIM IMS 00 01       Card removed   # unused companion slot
```

WebUI modem reader 推荐：

```text
PIN = 0
SWu = 0
IMS = 2
```

## 5. 回滚 modem bridge

```bash
sudo ./install.sh modem-bridge-disable
```

这会停止 bridge，移除 ModemManager/pcscd drop-in，并恢复之前备份的 distro VPCD reader 配置。
