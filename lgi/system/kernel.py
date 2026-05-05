import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lgi.config import KernelConfig


OUTPUT_DIR = Path("/tmp/lgi-gentoo")
KERNEL_CONFIG_PATH = OUTPUT_DIR / "kernel.config"


class KernelConfigError(RuntimeError):
    pass


@dataclass
class GentooKernelSource:
    source_dir: Path
    work_dir: Path


ProgressCallback = Callable[[int, str], None]


def configure_gentoo_kernel(
    kernel: KernelConfig,
    progress: ProgressCallback | None = None,
) -> Path:
    source = prepare_gentoo_kernel_source(kernel, progress=progress)
    try:
        result = subprocess.run(["make", "menuconfig"], cwd=source.source_dir, check=False)
        if result.returncode != 0:
            raise KernelConfigError(f"make menuconfig exited with status {result.returncode}.")

        source_config = source.source_dir / ".config"
        if not source_config.exists():
            raise KernelConfigError("Kernel menuconfig completed but did not create a .config file.")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_config, KERNEL_CONFIG_PATH)
        kernel.saved_config_path = str(KERNEL_CONFIG_PATH)
        return KERNEL_CONFIG_PATH
    finally:
        shutil.rmtree(source.work_dir, ignore_errors=True)


def prepare_gentoo_kernel_source(
    kernel: KernelConfig,
    progress: ProgressCallback | None = None,
) -> GentooKernelSource:
    _require_tools()
    _progress(progress, 1, "Creating temporary kernel work directory")
    work_dir = Path(tempfile.mkdtemp(prefix="lgi-gentoo-sources-"))
    downloads = work_dir / "downloads"
    patches = work_dir / "patches"
    downloads.mkdir()
    patches.mkdir()

    try:
        base_version = _base_kernel_version(kernel.source_version)
        _progress(progress, 5, f"Fetching linux-{base_version}.tar.xz")
        linux_tarball = _download_or_copy(
            f"linux-{base_version}.tar.xz",
            _linux_urls(base_version),
            downloads,
            progress=progress,
            progress_start=5,
            progress_end=45,
        )
        _progress(progress, 46, f"Unpacking {linux_tarball.name}")
        with tarfile.open(linux_tarball) as archive:
            _safe_extract(archive, work_dir)

        source_dir = work_dir / f"linux-{base_version}"
        if not source_dir.exists():
            raise KernelConfigError(f"Expected source directory {source_dir} after unpacking {linux_tarball.name}.")

        patchsets = ["base", "extras"]
        if kernel.include_experimental_patches:
            patchsets.append("experimental")

        patch_fetch_start = 52
        patch_fetch_span = 18
        for patchset in patchsets:
            tarball_name = f"genpatches-{_major_minor(kernel.source_version)}-{kernel.genpatches_version}.{patchset}.tar.xz"
            index = patchsets.index(patchset)
            start = patch_fetch_start + (patch_fetch_span * index // len(patchsets))
            end = patch_fetch_start + (patch_fetch_span * (index + 1) // len(patchsets))
            _progress(progress, start, f"Fetching {tarball_name}")
            patch_tarball = _download_or_copy(
                tarball_name,
                _genpatches_urls(tarball_name),
                downloads,
                progress=progress,
                progress_start=start,
                progress_end=end,
            )
            _progress(progress, end, f"Extracting {tarball_name}")
            _extract_patch_tarball(patch_tarball, patches / patchset)

        _progress(progress, 72, "Applying Gentoo kernel patches")
        _apply_patches(source_dir, patches, progress=progress, progress_start=72, progress_end=96)
        _progress(progress, 98, "Kernel source tree is ready")
        return GentooKernelSource(source_dir=source_dir, work_dir=work_dir)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def _require_tools() -> None:
    missing = [tool for tool in ("make", "patch") if shutil.which(tool) is None]
    if missing:
        raise KernelConfigError("Missing required tool(s): " + ", ".join(missing))


def _download_or_copy(
    filename: str,
    urls: list[str],
    output_dir: Path,
    *,
    progress: ProgressCallback | None = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> Path:
    local = _local_distfile(filename)
    destination = output_dir / filename
    if local is not None:
        _progress(progress, progress_start, f"Using cached {filename}")
        shutil.copy2(local, destination)
        _progress(progress, progress_end, f"Copied cached {filename}")
        return destination

    errors: list[str] = []
    for url in urls:
        try:
            urllib.request.urlretrieve(
                url,
                destination,
                reporthook=_download_reporthook(progress, progress_start, progress_end, f"Downloading {filename}"),
            )
            _progress(progress, progress_end, f"Downloaded {filename}")
            return destination
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise KernelConfigError(f"Could not download {filename}.\n" + "\n".join(errors))


def _local_distfile(filename: str) -> Path | None:
    for directory in (Path("/var/cache/distfiles"), Path("/usr/portage/distfiles")):
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def _extract_patch_tarball(tarball: Path, destination: Path) -> None:
    destination.mkdir()
    with tarfile.open(tarball) as archive:
        _safe_extract(archive, destination)


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if os.path.commonpath([destination, target]) != str(destination):
            raise KernelConfigError(f"Refusing unsafe tar member: {member.name}")
    archive.extractall(destination)


def _apply_patches(
    source_dir: Path,
    patches_dir: Path,
    *,
    progress: ProgressCallback | None = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> None:
    patch_files = sorted(p for p in patches_dir.rglob("*.patch") if p.is_file())
    total = max(1, len(patch_files))
    for idx, patch_file in enumerate(patch_files):
        percent = progress_start + ((progress_end - progress_start) * idx // total)
        _progress(progress, percent, f"Applying {patch_file.name}")
        result = subprocess.run(
            ["patch", "-p1", "-i", str(patch_file)],
            cwd=source_dir,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            raise KernelConfigError(f"Failed to apply {patch_file.name}:\n{result.stdout}")
    _progress(progress, progress_end, "Finished applying Gentoo patches")


def _linux_urls(base_version: str) -> list[str]:
    major = base_version.split(".", 1)[0]
    return [
        f"https://cdn.kernel.org/pub/linux/kernel/v{major}.x/linux-{base_version}.tar.xz",
        f"https://www.kernel.org/pub/linux/kernel/v{major}.x/linux-{base_version}.tar.xz",
        f"https://distfiles.gentoo.org/distfiles/linux-{base_version}.tar.xz",
    ]


def _genpatches_urls(filename: str) -> list[str]:
    return [
        f"https://dev.gentoo.org/~alicef/genpatches/tarballs/{filename}",
        f"https://dev.gentoo.org/~mpagano/genpatches/tarballs/{filename}",
        f"https://distfiles.gentoo.org/distfiles/{filename}",
    ]


def _base_kernel_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) < 2:
        raise KernelConfigError(f"Invalid kernel version: {version}")
    return ".".join(parts[:2])


def _major_minor(version: str) -> str:
    return _base_kernel_version(version)


def _progress(progress: ProgressCallback | None, percent: int, message: str) -> None:
    if progress is not None:
        progress(max(0, min(100, percent)), message)


def _download_reporthook(
    progress: ProgressCallback | None,
    start: int,
    end: int,
    message: str,
) -> Callable[[int, int, int], None]:
    last_percent = -1

    def report(block_count: int, block_size: int, total_size: int) -> None:
        nonlocal last_percent
        if progress is None or total_size <= 0:
            return
        downloaded = min(block_count * block_size, total_size)
        span = end - start
        percent = start + int(span * downloaded / total_size)
        if percent != last_percent:
            last_percent = percent
            progress(max(start, min(end, percent)), message)

    return report
