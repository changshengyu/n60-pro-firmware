#!/bin/sh
set -eu
if [ "$#" != 1 ]; then
    echo "Usage: sh install-docker.sh /mnt/your-external-disk" >&2
    exit 1
fi
storage="${1%/}"
[ -n "$storage" ] && [ "$storage" != / ] || exit 1
case "$storage" in *' '*|*'\t'*) echo 'Use a mount path without whitespace.' >&2; exit 1;; esac
fstype="$(awk -v p="$storage" '$2 == p {print $3}' /proc/mounts)"
if [ "$fstype" != ext4 ]; then
    echo 'Expected an already mounted ext4 external disk. This script never formats storage.' >&2
    exit 1
fi
here="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
[ -f "$here/SHA256SUMS" ] && (cd "$here" && sha256sum -c SHA256SUMS)
opkg install "$here"/*.ipk
/etc/init.d/dockerd stop || true
/etc/init.d/dockerd disable || true
mkdir -p "$storage/docker"
uci set dockerd.globals.data_root="$storage/docker"
uci commit dockerd
echo "Installed matching Docker packages; data root: $storage/docker"
echo 'Docker remains stopped. Verify the mount persists across reboot before enabling it.'
echo 'Then run: /etc/init.d/dockerd enable && /etc/init.d/dockerd start'
