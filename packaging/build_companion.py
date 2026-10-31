"""Build a self-contained Windows companion; never bundle local data or secrets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def runtime_files():
    files = [ROOT / "docker-compose.local.yml"]
    files.extend(ROOT / "backend" / name for name in ["Dockerfile", "requirements.txt", "run.py", "celery_worker.py", ".dockerignore"])
    files.extend((ROOT / "backend" / "app").rglob("*.py"))
    return sorted(files)


def stage_runtime(target, image=None):
    if image and not re.fullmatch(r"ghcr\.io/[a-z0-9_./-]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("Use an immutable GHCR image digest.")
    names = []
    for source in runtime_files():
        name = source.relative_to(ROOT)
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        names.append(name.as_posix())
    (target / "manifest.json").write_text(json.dumps({"files": names, "image": image}, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Published processing image, pinned by digest. Omit for source-build preview.")
    parser.add_argument("--iscc", type=Path, help="Optional path to Inno Setup's ISCC.exe.")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Build Windows binaries on Windows.")
    build = ROOT / ".pytest_cache" / "companion-build"
    output = ROOT / "dist" / "companion"
    build.mkdir(parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="runtime-", dir=build))
    stage_runtime(runtime, args.image)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "SubtitleD-Companion", "--distpath", str(output), "--workpath", str(build / "work"),
        "--specpath", str(build), "--add-data", f"{runtime};runtime", "--hidden-import", "pystray._win32",
        "--collect-all", "pystray", str(ROOT / "companion.py"),
    ], cwd=ROOT, check=True)
    app = output / "SubtitleD-Companion"
    shutil.copyfile(ROOT / "packaging" / "Install-Companion.cmd", app / "Install-Companion.cmd")
    shutil.copyfile(ROOT / "packaging" / "README.txt", app / "README.txt")
    shutil.make_archive(str(output / "SubtitleD-Companion-Windows"), "zip", app)
    if args.iscc:
        subprocess.run([str(args.iscc), f"/DSourceDir={app}", f"/DOutputDir={output}", str(ROOT / "packaging" / "companion.iss")], check=True)
    checksums = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.suffix in {".zip", ".exe"}:
            checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(f"Companion build ready: {output}")


if __name__ == "__main__":
    main()
