# Kyle Rabago

Course: IS 2053

Project Title: LGI (Larry's Gentoo Installer)

## Program Overview

LGI is a Python-based terminal installer for Gentoo Linux. The program guides a user through disk setup, filesystem selection, init system selection, system settings, kernel options, and final installation. It generates the required configuration files and uses Ansible playbooks to perform the outside live environment setup and the inside chroot installation steps.

The goal of the program is to make a Gentoo install more repeatable while still giving the user control over important choices such as disk layout, root partition, EFI partition, filesystem, init system, kernel type, and make.conf settings.

## Key Features

- Dialog-based terminal interface for configuring the install.
- Automatic or manual disk setup support.
- Generated Gentoo `vars.yml` and `make.conf` files.
- Ansible-driven outside and chroot install phases.
- Stage3 download and extraction.
- Portage tree sync and profile selection.
- CPU flag generation for Portage package.use settings.
- Binary or manual kernel install support.
- GRUB bootloader setup for EFI and BIOS/MBR systems.
- Final bootability checks for kernel, initramfs, GRUB configuration, and fstab.
- Post-install menu with options to reboot, enter the chroot shell, or select a future QOL tweaks option.

## Changes from Milestone 2

- Added a more complete chroot installation phase.
- Added bootloader installation and GRUB configuration.
- Added support for both EFI and BIOS/MBR boot targets.
- Added automatic cleanup of stale mounts when rerunning automatic disk management.
- Improved chroot output so installation progress is easier to follow.
- Added `dhcpcd` networking setup instead of using a heavier network manager.
- Added checks to confirm the installed system has the expected boot files before finishing.

## Challenges Encountered and Resolved

One challenge was getting the outside Ansible playbook to transition cleanly into the chroot phase. The early version captured too much output as one large Ansible result, which made debugging difficult. This was resolved by having the Python runner start the chroot phase directly and by improving how command output is streamed.

Another challenge was making the installer safe to rerun after a failed or interrupted install. Previous mount points could remain active and cause disk formatting or mounting errors. This was resolved by adding lazy unmount cleanup for the target mount tree and selected install partitions before automatic disk management starts.

A third challenge was kernel installation from inside a chroot. The Gentoo binary kernel uses installkernel and dracut, which require a target kernel command line. This was resolved by generating `/etc/cmdline` from the target root partition UUID before installing the kernel.
