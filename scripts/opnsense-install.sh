#!/bin/sh
# Run only inside the seeded OPNsense live system, on its single empty VM disk.
set -eu
BASE=/usr/local/share/ansible-opnsense
export PATH="${BASE}/shim:/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/bin:/usr/local/sbin"
export TERM=xterm nonInteractive=1
/usr/local/bin/php "${BASE}/inspect.php" > /tmp/ansible-install-state.json
# This also checks every MAC-to-interface mapping, the management address and seed ID.
grep -q '"state":"live"' /tmp/ansible-install-state.json || exit 1
[ "$(sysctl -n kern.disks | tr ' ' '\n' | grep -v '^cd[0-9][0-9]*$')" = da0 ] || { echo 'Unexpected disk set' >&2; exit 1; }
[ "$(diskinfo da0 | awk '{print $3}')" = 34359738368 ] || exit 1
# Never erase a partition table, including an interrupted installation.
if gpart show da0 >/dev/null 2>&1; then
    echo 'Disk already partitioned; refusing to reinstall' >&2
    exit 1
fi
mkdir /tmp/ansible-install.lock || { echo 'Installation already started' >&2; exit 1; }
export BSDINSTALL_CHROOT=/mnt BSDINSTALL_TMPETC=/tmp/bsdinstall_etc
export BSDINSTALL_TMPBOOT=/tmp/bsdinstall_boot
export BSDINSTALL_LOG=/var/log/ansible-install.log
export ZFSBOOT_DISKS=da0 ZFSBOOT_POOL_NAME=zroot ZFSBOOT_VDEV_TYPE=stripe
export ZFSBOOT_PARTITION_SCHEME=GPT ZFSBOOT_BOOT_TYPE=UEFI
export ZFSBOOT_SWAP_SIZE=2g ZFSBOOT_CONFIRM_LAYOUT=
mkdir -p "$BSDINSTALL_TMPETC" "$BSDINSTALL_TMPBOOT"
export PATH_FSTAB=/tmp/bsdinstall_etc/fstab
: > "$PATH_FSTAB"
: > /tmp/bsdinstall-esps
timeout -k 30 600 bsdinstall opnsense-zfs >> "$BSDINSTALL_LOG" 2>&1
timeout -k 30 120 bsdinstall mount >> "$BSDINSTALL_LOG" 2>&1
timeout -k 30 1800 bsdinstall opnsense-install >> "$BSDINSTALL_LOG" 2>&1
timeout -k 30 120 bsdinstall bootconfig >> "$BSDINSTALL_LOG" 2>&1
timeout -k 30 120 bsdinstall entropy >> "$BSDINSTALL_LOG" 2>&1
# Mark only the installed target, after the vendor clone and bootloader steps succeeded.
cp "${BASE}/intent.json" "$BSDINSTALL_CHROOT/conf/ansible-install.json"
chmod 600 "$BSDINSTALL_CHROOT/conf/ansible-install.json"
sync
bsdinstall umount >> "$BSDINSTALL_LOG" 2>&1
printf '%s\n' 'ANSIBLE_DISK_INSTALLED'
# The playbook records completion before requesting clean shutdown through Proxmox.
