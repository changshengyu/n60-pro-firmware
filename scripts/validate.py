#!/usr/bin/env python3
"""Fail before publishing when the device, wireless or container config differs."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'

def values(path):
    result = {}
    for line in path.read_text().splitlines():
        m = re.match(r'(CONFIG_[^=]+)=(.*)', line)
        if m:
            result[m[1]] = m[2]
    return result

def require(cfg, names, value='y'):
    errors = [f'{name}: expected {value}, got {cfg.get(name, "n")}'
              for name in names if cfg.get(name) != value]
    if errors:
        raise RuntimeError('\n'.join(errors))

def check_config():
    cfg = values(BUILD / '.config')
    require(cfg, ['CONFIG_TARGET_mediatek_filogic',
        'CONFIG_TARGET_mediatek_filogic_DEVICE_netcore_n60-pro',
        'CONFIG_PACKAGE_luci-app-passwall', 'CONFIG_PACKAGE_luci-app-store',
        'CONFIG_PACKAGE_xray-core', 'CONFIG_PACKAGE_sing-box',
        'CONFIG_PACKAGE_kmod-mt_wifi', 'CONFIG_PACKAGE_mtwifi-cfg',
        'CONFIG_PACKAGE_luci-app-mtwifi-cfg', 'CONFIG_MTK_FIRST_IF_IPAILNA',
        'CONFIG_PACKAGE_kmod-fs-cifs', 'CONFIG_PACKAGE_kmod-fs-ext4',
        'CONFIG_PACKAGE_kmod-usb-storage-uas', 'CONFIG_PACKAGE_block-mount',
        'CONFIG_PACKAGE_kmod-veth', 'CONFIG_PACKAGE_kmod-br-netfilter',
        'CONFIG_PACKAGE_kmod-nft-tproxy', 'CONFIG_KERNEL_CGROUPS',
        'CONFIG_KERNEL_MEMCG', 'CONFIG_KERNEL_CGROUP_PIDS',
        'CONFIG_KERNEL_NAMESPACES', 'CONFIG_KERNEL_NET_NS', 'CONFIG_KERNEL_SECCOMP'])
    require(cfg, ['CONFIG_PACKAGE_docker', 'CONFIG_PACKAGE_dockerd',
                  'CONFIG_PACKAGE_containerd', 'CONFIG_PACKAGE_runc'], 'm')
    for name in ('CONFIG_TARGET_MULTI_PROFILE', 'CONFIG_TARGET_mediatek_mt7986',
                 'CONFIG_MTK_MT7986_NEW_FW', 'CONFIG_PACKAGE_kmod-mt7915e',
                 'CONFIG_PACKAGE_kmod-mt7986-firmware', 'CONFIG_PACKAGE_wpad-openssl'):
        if cfg.get(name) in ('y', 'm'):
            raise RuntimeError(f'Conflicting or obsolete selection: {name}')
    selected = [k for k,v in cfg.items() if k.startswith('CONFIG_TARGET_') and
                '_DEVICE_' in k and v == 'y']
    assert selected == ['CONFIG_TARGET_mediatek_filogic_DEVICE_netcore_n60-pro'], selected
    dts = (BUILD / 'target/linux/mediatek/dts/mt7986a-netcore-n60-pro.dts').read_text()
    for pattern in (r'compatible\s*=\s*"netcore,n60-pro"',
                    r'reg\s*=\s*<0x180000\s+0x200000>',
                    r'reg\s*=\s*<0x380000\s+0x200000>',
                    r'reg\s*=\s*<0x0?580000\s+0x7280000>'):
        if not re.search(pattern, dts):
            raise RuntimeError(f'Unexpected N60 PRO partition definition: {pattern}')
    print('PASS: single N60 PRO, 128 MiB layout, MTK high-power, CIFS, USB, Docker prerequisites')

def check_kernel():
    paths = list((BUILD / 'build_dir/target-aarch64_cortex-a53_musl').glob('linux-mediatek_filogic/linux-6.6*/.config'))
    if len(paths) != 1:
        paths = list((BUILD / 'build_dir').glob('target-*/linux-mediatek_filogic/linux-6.6*/.config'))
    if len(paths) != 1:
        raise RuntimeError(f'Expected one compiled Linux 6.6 config, found {paths}')
    cfg = values(paths[0])
    require(cfg, ['CONFIG_CGROUPS', 'CONFIG_CGROUP_PIDS', 'CONFIG_MEMCG',
        'CONFIG_NAMESPACES', 'CONFIG_NET_NS', 'CONFIG_PID_NS', 'CONFIG_IPC_NS',
        'CONFIG_UTS_NS', 'CONFIG_SECCOMP', 'CONFIG_SECCOMP_FILTER', 'CONFIG_OVERLAY_FS'])
    for key in ('CONFIG_CIFS', 'CONFIG_EXT4_FS', 'CONFIG_VETH', 'CONFIG_BRIDGE_NETFILTER'):
        if cfg.get(key) not in ('y', 'm'):
            raise RuntimeError(f'Missing compiled kernel capability: {key}')
    (ROOT / 'logs/kernel.config').write_text(paths[0].read_text())
    print('PASS: compiled kernel supports CIFS, overlayfs, namespaces, cgroups and container networking')

if __name__ == '__main__':
    check_config()
    if len(sys.argv) > 1 and sys.argv[1] == 'kernel':
        check_kernel()
