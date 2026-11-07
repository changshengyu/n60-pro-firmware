#!/usr/bin/env python3
"""Fetch pinned sources and create a single-device configuration."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'sources.lock.json').read_text())
BUILD = ROOT / 'build'

def run(*args, cwd=None):
    print('+', *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)

def fetch(name, spec, dest):
    if not (dest / '.git').exists():
        dest.mkdir(parents=True, exist_ok=True)
        run('git', 'init', dest)
        run('git', 'remote', 'add', 'origin', spec['url'], cwd=dest)
        if spec.get('subdir'):
            run('git', 'sparse-checkout', 'init', '--cone', cwd=dest)
            run('git', 'sparse-checkout', 'set', spec['subdir'], cwd=dest)
    run('git', 'fetch', '--depth=1', 'origin', spec['commit'], cwd=dest)
    run('git', 'checkout', '--detach', 'FETCH_HEAD', cwd=dest)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=dest, text=True).strip()
    assert actual == spec['commit'], (name, actual)

def main():
    fetch('openwrt', LOCK['repositories']['openwrt'], BUILD)
    feeds = []
    for name, spec in LOCK['repositories'].items():
        if name == 'openwrt':
            continue
        dest = ROOT / 'sources' / name
        fetch(name, spec, dest)
        if not spec.get('role'):
            feeds.append(f'src-link {name} {dest}')
    # Xray 26.10.31 requires Go 1.27; the 24.10 feed provides Go 1.23.
    # Backport only the upstream Go recipes, not the entire master package feed.
    golang = ROOT / 'sources/packages/lang/golang'
    shutil.rmtree(golang)
    shutil.copytree(ROOT / 'sources/toolchain_golang/lang/golang', golang)
    (BUILD / 'feeds.conf').write_text('\n'.join(feeds) + '\n')
    # Only change the N60 PRO package selection. Preserve its DTS and partitions.
    path = BUILD / 'target/linux/mediatek/image/filogic.mk'
    text = path.read_text()
    match = re.search(r'define Device/netcore_n60-pro\n.*?\nendef', text, re.S)
    if not match:
        raise RuntimeError('N60 PRO device definition missing')
    block = match.group()
    block = re.sub(r'  DEVICE_PACKAGES := .*',
        '  DEVICE_PACKAGES := kmod-mt_wifi mtwifi-cfg luci-app-mtwifi-cfg '
        'kmod-usb3 automount kmod-usb-ledtrig-usbport', block)
    text = text[:match.start()] + block + text[match.end():]
    path.write_text(text)
    template = BUILD / 'defconfig/mt7975-ipailna-high-power.config'
    wireless = []
    for line in template.read_text().splitlines():
        if re.match(r'(?:# )?CONFIG_(MTK_|CONNINFRA_)', line):
            wireless.append(line)
    if '# CONFIG_MTK_MT7986_NEW_FW is not set' not in wireless:
        raise RuntimeError('Upstream high-power template changed: review required')
    (BUILD / '.config').write_text('\n'.join(wireless) + '\n' +
                                   (ROOT / 'config/profile.config').read_text())
    overlay = ROOT / 'files'
    run('cp', '-a', str(overlay) + '/.', BUILD / 'files')
    run('./scripts/feeds', 'update', '-a', cwd=BUILD)
    run('./scripts/feeds', 'install', '-a', cwd=BUILD)
    # Ensure the requested proxy cores replace identically named upstream feed recipes.
    run('./scripts/feeds', 'install', '-f', '-a', '-p', 'passwall_packages', cwd=BUILD)
    run('./scripts/feeds', 'install', '-f', '-a', '-p', 'passwall_luci', cwd=BUILD)
    run('./scripts/feeds', 'install', '-f', '-a', '-p', 'istore', cwd=BUILD)
    run('make', 'defconfig', cwd=BUILD)
    # Docker is built as optional userspace; its kernel dependencies belong in ROM.
    cfg = BUILD / '.config'
    cfg.write_text(re.sub(r'^(CONFIG_PACKAGE_kmod-[^=]+)=m$', r'\1=y',
                          cfg.read_text(), flags=re.M))
    run('make', 'defconfig', cwd=BUILD)
    run('python3', ROOT / 'scripts/validate.py', 'config')
    (ROOT / 'logs').mkdir(exist_ok=True)
    (ROOT / 'logs/resolved.config').write_text(cfg.read_text())
    diff = subprocess.check_output(['git', 'diff'], cwd=BUILD, text=True)
    (ROOT / 'logs/source.patch').write_text(diff)
    print('Pinned sources and resolved N60 PRO configuration ready.', flush=True)

if __name__ == '__main__':
    main()
