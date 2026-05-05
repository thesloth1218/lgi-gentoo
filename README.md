# lgi-gentoo

Larry's Gentoo Installer is a TUI-driven Gentoo install orchestrator.

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

## GitHub

Initialize and push the repo with:

```sh
git add .
git commit -m "Initial lgi-gentoo installer"
git branch -M main
git remote add origin git@github.com:YOUR_USER/lgi-gentoo.git
git push -u origin main
```

Use the HTTPS remote instead if SSH keys are not set up:

```sh
git remote add origin https://github.com/YOUR_USER/lgi-gentoo.git
```

