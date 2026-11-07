#!/usr/bin/env python3
"""Verify the image and package a dependency-complete offline Docker bundle."""
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
OUT = ROOT / 'release'

def control_fields(text):
    result = {}
    key = None
    for line in text.splitlines():
        if line.startswith((' ', '\t')) and key:
            result[key] += ' ' + line.strip()
        elif ': ' in line:
            key, value = line.split(': ', 1)
            result[key] = value
    return result

def ipk_control(path):
    data = path.read_bytes()
    control = None
    if data.startswith(b'!<arch>\n'):
        pos = 8
        while pos + 60 <= len(data):
            header = data[pos:pos+60]
            size = int(header[48:58].strip())
            name = header[:16].decode().strip().rstrip('/')
            pos += 60
            if name.startswith('control.tar'):
                control = data[pos:pos+size]
                break
            pos += size + size % 2
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as ar:
            member = next(m for m in ar if Path(m.name).name.startswith('control.tar'))
            control = ar.extractfile(member).read()
    if control is None:
        raise RuntimeError(f'No control archive: {path}')
    with tarfile.open(fileobj=io.BytesIO(control), mode='r:*') as ar:
        member = next(m for m in ar if m.name.removeprefix('./') == 'control')
        return control_fields(ar.extractfile(member).read().decode())

def name_only(expr):
    return re.split(r'\s|\(', expr.strip(), maxsplit=1)[0]

def main():
    OUT.mkdir(exist_ok=True)
    target = BUILD / 'bin/targets/mediatek/filogic'
    images = list(target.glob('*netcore_n60-pro*sysupgrade.bin'))
    if len(images) != 1:
        raise RuntimeError(f'Expected exactly one N60 PRO sysupgrade image: {images}')
    image = images[0]
    if image.stat().st_size > 100 * 1024**2:
        raise RuntimeError('Image exceeds conservative 100 MiB ceiling for stock 128 MiB NAND')
    with tarfile.open(image, mode='r:*') as ar:
        control = ar.extractfile('sysupgrade-netcore_n60-pro/CONTROL').read().decode()
        if control.strip() != 'BOARD=netcore_n60-pro':
            raise RuntimeError(f'Wrong image board: {control}')
        kernel = ar.extractfile('sysupgrade-netcore_n60-pro/kernel').read(4)
        root = ar.extractfile('sysupgrade-netcore_n60-pro/root').read(4)
        assert kernel == b'\xd0\x0d\xfe\xed', 'Expected FIT kernel'
        assert root == b'hsqs', 'Expected SquashFS root'
    fwtool = BUILD / 'staging_dir/host/bin/fwtool'
    metadata = OUT / 'image-metadata.json'
    subprocess.run([str(fwtool), '-i', str(metadata), str(image)], check=True)
    meta = json.loads(metadata.read_text())
    supported = meta.get('supported_devices', []) + meta.get('new_supported_devices', [])
    if not {'netcore,n60-pro', 'netcore_n60-pro'}.intersection(supported):
        raise RuntimeError(f'N60 PRO not present in image metadata: {supported}')
    manifests = list(target.glob('*netcore_n60-pro*.manifest'))
    if len(manifests) != 1:
        raise RuntimeError(f'Expected one firmware manifest: {manifests}')
    installed = {}
    for line in manifests[0].read_text().splitlines():
        if ' - ' in line:
            name, version = line.split(' - ', 1)
            installed[name] = version
    required = ['kernel','kmod-mt_wifi','luci-app-mtwifi-cfg','luci-app-passwall',
                'xray-core','sing-box','luci-app-store','kmod-fs-cifs','kmod-fs-ext4',
                'kmod-usb-storage-uas','block-mount','kmod-veth','kmod-br-netfilter',
                'mwan3','luci-app-mwan3','lucky','luci-app-lucky','ksmbd-server',
                'kmod-fs-ksmbd','luci-app-upnp']
    absent = set(required) - installed.keys()
    if absent:
        raise RuntimeError(f'Required firmware packages missing: {sorted(absent)}')
    if not installed['kernel'].startswith('6.6.'):
        raise RuntimeError(f'Wrong kernel: {installed["kernel"]}')
    if not installed['luci-app-passwall'].startswith('26.11.3'):
        raise RuntimeError(f'Unexpected PassWall version: {installed["luci-app-passwall"]}')
    if {'kmod-mt7915e', 'dockerd', 'containerd', 'runc'}.intersection(installed):
        raise RuntimeError('Unexpected MT76 driver or optional Docker userspace in firmware')
    package_dir = OUT / 'packages'
    package_dir.mkdir(exist_ok=True)
    packages = {}
    providers = {}
    for path in sorted((BUILD / 'bin').rglob('*.ipk')):
        info = ipk_control(path)
        name = info['Package']
        if info.get('Architecture') not in ('all','noarch','aarch64_cortex-a53'):
            continue
        dest = package_dir / path.name
        if dest.exists():
            if hashlib.sha256(dest.read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest():
                raise RuntimeError(f'Conflicting package filename: {path.name}')
        else:
            shutil.copy2(path, dest)
        if name in packages and packages[name][1]['Version'] != info['Version']:
            raise RuntimeError(f'Multiple package versions in one build: {name}')
        packages[name] = (dest, info)
        for provision in info.get('Provides','').split(','):
            if provision.strip():
                providers.setdefault(name_only(provision), name)
    installed_providers = set(installed)
    for name in installed:
        if name in packages:
            installed_providers.update(name_only(x) for x in packages[name][1].get('Provides','').split(',') if x.strip())
    def closure(roots):
        pending = list(roots)
        selected = set()
        while pending:
            name = pending.pop()
            if name in installed_providers or name in selected:
                continue
            name = name if name in packages else providers.get(name, name)
            if name not in packages:
                raise RuntimeError(f'Offline dependency not built: {name}')
            if name in selected:
                continue
            selected.add(name)
            for group in packages[name][1].get('Depends','').split(','):
                alternatives = [name_only(a) for a in group.split('|') if a.strip()]
                if not alternatives or any(a in installed_providers for a in alternatives):
                    continue
                candidate = next((a for a in alternatives if a in packages or a in providers), None)
                if candidate is None:
                    raise RuntimeError(f'Unresolved dependency of {name}: {group}')
                pending.append(candidate)
        return selected
    roots = ['docker','dockerd','containerd','runc','luci-app-dockerman','luci-i18n-dockerman-zh-cn']
    selected = closure(roots)
    docker_dir = OUT / 'docker-offline'
    docker_dir.mkdir(exist_ok=True)
    for name in selected:
        shutil.copy2(packages[name][0], docker_dir / packages[name][0].name)
    shutil.copy2(ROOT / 'scripts/install-docker.sh', docker_dir / 'install-docker.sh')
    (docker_dir / 'SHA256SUMS').write_text('\n'.join(
        f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}'
        for p in sorted(docker_dir.glob('*.ipk'))) + '\n')
    optional_bundles = {}
    for app, app_roots in {
        'ddns-go': ['ddns-go','luci-app-ddns-go','luci-i18n-ddns-go-zh-cn'],
        'zerotier': ['zerotier','luci-app-zerotier','luci-i18n-zerotier-zh-cn'],
        'usb-print': ['p910nd','luci-app-p910nd','luci-i18n-p910nd-zh-cn'],
        'homeproxy': ['luci-app-homeproxy','luci-i18n-homeproxy-zh-cn'],
        'openclash': ['luci-app-openclash'],
    }.items():
        app_packages = closure(app_roots)
        dest = OUT / 'optional-offline' / app
        dest.mkdir(parents=True, exist_ok=True)
        for name in app_packages:
            shutil.copy2(packages[name][0], dest / packages[name][0].name)
        optional_bundles[app] = sorted(app_packages)
    shutil.copy2(image, OUT / image.name)
    shutil.copy2(manifests[0], OUT / manifests[0].name)
    shutil.copy2(ROOT / 'sources.lock.json', OUT / 'sources.lock.json')
    shutil.copy2(BUILD / '.config', OUT / 'resolved.config')
    shutil.copy2(ROOT / 'logs/kernel.config', OUT / 'kernel.config')
    shutil.copy2(ROOT / 'logs/source.patch', OUT / 'source.patch')
    shutil.copy2(ROOT / 'README.md', OUT / 'README.md')
    summary = {'board':'netcore,n60-pro','flash_bytes':0x08000000,
        'ubi_bytes':0x07280000,'image':image.name,'image_bytes':image.stat().st_size,
        'kernel':installed['kernel'],'passwall':installed['luci-app-passwall'],
        'istore':installed['luci-app-store'],'offline_docker_packages':sorted(selected),
        'optional_bundles':optional_bundles,
        'installed':installed}
    (OUT / 'validation.json').write_text(json.dumps(summary, indent=2) + '\n')
    checksums = []
    for path in sorted(OUT.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS':
            checksums.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(OUT)}')
    (OUT / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
    print(json.dumps({k:v for k,v in summary.items() if k != 'installed'}, indent=2))

if __name__ == '__main__':
    main()
