#!/bin/bash

# Format the disk if not already formatted
if ! lsblk | grep -q "/mnt/disks/k3s"; then
    mkfs.ext4 -m 0 -F -E lazy_itable_init=0,lazy_journal_init=0,discard /dev/disk/by-id/google-k3s-disk
    mkdir -p /mnt/disks/k3s
    mount -o discard,defaults /dev/disk/by-id/google-k3s-disk /mnt/disks/k3s
    chmod a+w /mnt/disks/k3s
fi

# ensure only run once
if [[ -f /etc/startup_was_launched ]]; then exit 0; fi
touch /etc/startup_was_launched

# apt install
apt update
apt install -y ncdu htop

# helm install
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh
/bin/bash get_helm.sh

# bashrc config
rc=/root/.bashrc
echo "alias l='ls -lah'" >> $rc
echo "alias ll='ls -lh'" >> $rc
echo "alias k=kubectl" >> $rc
echo "export dry='--dry-run=client'" >> $rc
echo "export o='-oyaml'" >> $rc
echo "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml" >> $rc

# Get the external IP of this VM
EXTERNAL_IP=$(curl -s http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip -H "Metadata-Flavor: Google")

# Install k3s and configure it to use the persistent disk for data storage
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--data-dir /mnt/disks/k3s --tls-san ${EXTERNAL_IP} --bind-address 0.0.0.0" sh -