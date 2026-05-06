#!/bin/bash
set -euo pipefail
export PYTHONUNBUFFERED=1
export ANSIBLE_FORCE_COLOR=1
export TERM=${TERM:-xterm-256color}
if [ -z "${LGI_TTY:-}" ] && [ -t 1 ]; then
    LGI_TTY="$(tty)"
    export LGI_TTY
fi

mkdir -p /var/log
exec > >(tee -a /var/log/chroot-ansible.log) 2>&1

cd /root/lgi-gentoo

export ANSIBLE_CONFIG=/root/lgi-gentoo/ansible/ansible.cfg
export ANSIBLE_LOCAL_TEMP=/tmp/lgi-gentoo/ansible-local-tmp
export ANSIBLE_REMOTE_TEMP=/tmp/lgi-gentoo/ansible-remote-tmp
export TMPDIR=/tmp/lgi-gentoo
export ANSIBLE_STDOUT_CALLBACK=default
export ANSIBLE_DISPLAY_ARGS_TO_STDOUT=False
export ANSIBLE_LOAD_CALLBACK_PLUGINS=True

mkdir -p "$ANSIBLE_LOCAL_TEMP" "$ANSIBLE_REMOTE_TEMP" "$TMPDIR"

if [ -x .lgi-ansible/bin/ansible-playbook ]; then
    ANSIBLE_PLAYBOOK=.lgi-ansible/bin/ansible-playbook
elif command -v ansible-playbook >/dev/null 2>&1; then
    ANSIBLE_PLAYBOOK=ansible-playbook
else
    emerge --oneshot --noreplace app-admin/ansible-core
    ANSIBLE_PLAYBOOK=ansible-playbook
fi

exec "$ANSIBLE_PLAYBOOK" -i ansible/inventory/chroot.ini ansible/playbooks/chroot.yml
