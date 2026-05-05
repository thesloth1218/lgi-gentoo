# LGI-Gentoo

Larry's Gentoo Installer is a Python TUI installer for Gentoo. It is intended
to get a machine to a base install with support for custom kernel `.config`
files, automatic disk management, and Ansible-driven outside/chroot phases.

## Live CD test package

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

## Git clone workflow

On a live CD with `git` and network access:

```sh
git clone https://github.com/TheSloth1218/LGI-Gentoo.git
cd LGI-Gentoo
python3 main.py
```

## Development

Generate installer outputs:

```sh
python3 main.py generate
```

Run the outside playbook:

```sh
python3 main.py install
```

