# LGI-Gentoo

Larry's Gentoo Installer is a Python TUI installer for Gentoo. It is intended
to get a machine to a base install with support for custom kernel `.config`
files, automatic disk management, and Ansible-driven outside/chroot phases.

Clone to livecd and run python main.py

FOR using existing configs from github/etc make sure wget can fetch them ie raw.githubusercontent links work great

Feel free to make issues and Ill try to fix them but its meant to be very basic 


## TESTING/DEV:

Live CD test package

Build a portable runner package:

```sh
python3 main.py package-runner
```

The package is written to:

```text
/tmp/lgi-gentoo/lgi-gentoo-runner.tar.gz
```

On the live CD, extract and run it:

```sh
tar xzf lgi-gentoo-runner.tar.gz
cd lgi-gentoo
python3 main.py
```

```

