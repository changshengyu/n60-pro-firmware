# N60 PRO 6.6 固件构建

仅适用于 `netcore,n60-pro`，512 MiB 内存、128 MiB 原版 SPI NAND。

## 构建内容

- 固定 `sources.lock.json` 中的固件与全部软件源提交。
- 单独回移上游 Go 1.27 构建规则以支持最新 Xray；不整体混入 master 软件源。
- 6.6 内核；MTK 专有无线驱动；移植上游高功率模板中的无线参数。
- 单独选择 N60 PRO；移除该设备默认 MT76 包，避免两套驱动共存。
- PassWall 26.11.3-1 中文界面、Xray、sing-box；iStore 商店。
- 保留多 WAN（mwan3）、Lucky、轻量 ksmbd 网络共享、UPnP、HNAT/HQOS。
- DDNS-Go、ZeroTier、USB 打印、HomeProxy/OpenClash 管理插件另附依赖闭合的离线包。
- CIFS、USB/UAS、ext4、exFAT、挂载工具和 Docker 所需内核功能。
- Docker/containerd/runc/管理界面作为同批次离线安装包，不占基础固件空间。
- LAN 为 `192.168.6.1`；PassWall 默认不启用，导入自己的节点后再启用。
- iStore 与 GNU wget 使用 IPv4 下载，以对应原网络中已验证的 IPv6 超时问题；局域网 IPv6 仍保留。

这不是完整 iStoreOS，也不默认安装 iStoreX。CIFS 依赖已预装。
不会向固件写入任何用户密码、订阅链接或代理节点。

## GitHub Actions

在 Actions 中选择 **Build N60 PRO firmware**，手动运行。默认 2 个并行任务，使用 Ubuntu 22.04 x86_64。
先准备和验证配置，再下载并编译；编译失败会串行重试一次并上传完整日志。
成功产物仅在设备、分区、内核及包清单验证全部通过后上传。
后续构建使用源码下载、C/C++ 与 Go 编译缓存；不同版本的文件仍由上游哈希和编译缓存自身的内容校验区分。

Artifacts 包含：

- `*netcore_n60-pro*sysupgrade.bin`：完整固件。
- `packages/`：本次构建生成的匹配 IPK 包，尤其内核模块。
- `docker-offline/`：相对本固件依赖闭合的 Docker 安装包。
- `optional-offline/`：其他应用分目录的离线包。OpenClash 的 Mihomo 核心需在启用前由插件下载；不同透明代理一次只启用一个。
- `validation.json`、`image-metadata.json`、`SHA256SUMS`。
- 最终固件配置、内核配置、源码补丁、锁定版本文件。

源仓库的 `2410` 分支是 5.4 内核。此工程固定使用 6.6 分支的源码提交，
只从对应高功率模板导入 MTK/CONNINFRA 参数，不照搬旧目标或其他机型。
运行 `make defconfig` 后验证高功率选项以及单设备选择。

## 刷入前与迁移

构建成功只代表编译和静态检查通过，不代表已经完成实机测试。
Wi-Fi、2.5G 网口、硬件加速和 Docker/代理共存需要刷入后检查。

1. 将现有配置、已安装软件清单、Factory、BL2、FIP 等备份保存到电脑。
2. 核对完整固件校验值、板型和当前 U-Boot/分区；不要刷 N60 或硬改大闪存版本。
3. 跨 5.4/6.6 和无线驱动迁移建议干净配置。先在内部闪存启动新系统。
4. 旧 USB 扩展根分区包含旧软件和模块，不应直接挂载覆盖新系统。
5. 待内部系统和网络确认正常，再迁移个人设置、重新配置外接存储。

本项目不自动刷机，不格式化现有 U 盘，不改写 BL2/FIP/Factory。
固件元数据与分区不符时，不应强制跳过校验。

多 WAN 提供故障切换/负载均衡，不等于单连接带宽叠加；需要接入多条线路后配置。
网络共享集成 ksmbd，但不会自动将磁盘目录公开共享。

## 外接存储与 Docker

512 MiB RAM 适合少量轻量容器。USB 扩容不会增加 RAM。
建议将 Docker 数据放在已挂载的 ext4 分区，而不是内部 NAND。

先完成 USB extroot（扩展系统根分区），确认 `/` 可用空间至少 256 MiB。
仅挂载一个容器数据目录并不会增加 `/usr/bin` 安装 Docker 主程序所需的空间。
再将存储分区挂载到自己的目录（例如 `/mnt/usb`），确认重启后仍能挂载；
将 `docker-offline` 目录复制到路由器能访问的位置，然后执行：

```sh
sh /你的路径/docker-offline/install-docker.sh /mnt/usb
```

该脚本要求外接盘已经挂载为 ext4，且根分区有至少 256 MiB 可用空间，不会格式化磁盘。
它安装本次构建的包、设置数据目录并保持 Docker 停止。
确认挂载和网络规则后，再手动启用 Docker。

离线包只针对同次构建的固件。不要混装其他构建的 `kmod-*`，也不要全量 `opkg upgrade`。
代理与 Docker 都会设置防火墙规则；刷入后需要测试普通 LAN、容器 DNS/联网及 PassWall 分流。

## 在 Linux 本地复现

准备与 Actions 相同的依赖，在普通用户下运行：

```sh
python3 scripts/prepare.py
BUILD_JOBS=2 bash scripts/build.sh
```

编译目录至少预留约 60 GiB。首次构建耗时取决于源码下载和编译机器性能。
