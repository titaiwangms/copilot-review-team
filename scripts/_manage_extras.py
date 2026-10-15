#!/usr/bin/env python3
"""Install opt-in agents/instructions without managing other Copilot state."""
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile

MANIFEST = ".copilot-review-team-extras-manifest"
SOURCE = Path(__file__).resolve().parent.parent / "extras"


def valid_path(name):
    parts = PurePosixPath(name).parts
    if len(parts) != 2 or ".." in name:
        return False
    folder, filename = parts
    if folder == "agents":
        return re.fullmatch(r"local-[A-Za-z0-9._-]+\.agent\.md", filename) is not None
    if folder == "instructions":
        return re.fullmatch(
            r"copilot-review-team-[A-Za-z0-9_-]+\.instructions\.md", filename
        ) is not None
    return False


def check_target(home, name):
    target = home / name
    parent = target.parent
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise ValueError("unsafe parent directory: %s" % parent)
    if target.is_dir():
        raise ValueError("expected a file, found a directory: %s" % target)
    if target.exists() and not target.is_symlink() and not target.is_file():
        raise ValueError("expected a regular file or leaf symlink: %s" % target)
    return target


def read_manifest(home):
    path = home / MANIFEST
    if path.is_symlink():
        raise ValueError("extras manifest must not be a symlink: %s" % path)
    if not path.exists():
        return set()
    if not path.is_file():
        raise ValueError("extras manifest must be a file: %s" % path)
    names = set(path.read_text(encoding="utf-8").splitlines())
    for name in names:
        if not valid_path(name) or name != PurePosixPath(name).as_posix():
            raise ValueError("unsafe extras manifest entry: %r" % name)
    return names


def source_files(source):
    files = {}
    if source.is_symlink() or not source.is_dir():
        raise ValueError("extras source must be a directory: %s" % source)
    for folder, pattern in (
        ("agents", "local-*.agent.md"),
        ("instructions", "*.instructions.md"),
    ):
        directory = source / folder
        if directory.is_symlink():
            raise ValueError("extras source directory must not be a symlink: %s" % directory)
        for path in sorted(directory.glob(pattern)):
            name = path.relative_to(source).as_posix()
            if not valid_path(name) or path.is_symlink() or not path.is_file():
                raise ValueError("invalid extras source file: %s" % path)
            files[name] = path
    if not files:
        raise ValueError("no extras source files found: %s" % source)
    return files


def atomic_write(target, data, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-extras-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def manage(action, home, backup, source=SOURCE):
    home = Path(home).resolve()
    backup = Path(backup)
    backup = backup.parent.resolve() / backup.name
    if backup.parent != home or not re.fullmatch(r"\.backup-[A-Za-z0-9_-]+", backup.name):
        raise ValueError("backup directory must be a named child of Copilot home")
    if backup.is_symlink() or (backup.exists() and not backup.is_dir()):
        raise ValueError("unsafe backup directory: %s" % backup)
    previous = read_manifest(home)
    installing = action in ("install", "check")
    files = source_files(Path(source)) if installing else {}
    for name in previous | files.keys():
        check_target(home, name)
        destination = backup / name
        if destination.parent.is_symlink() or (
            destination.parent.exists() and not destination.parent.is_dir()
        ):
            raise ValueError("unsafe backup parent: %s" % destination.parent)
        if destination.exists() or destination.is_symlink():
            raise ValueError("backup destination already exists: %s" % destination)
    if action in ("check", "check-remove"):
        return

    def save(target, name):
        if target.exists() or target.is_symlink():
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination, follow_symlinks=False)

    for name, path in sorted(files.items()):
        target = home / name
        data = path.read_bytes()
        if not target.is_symlink() and target.is_file() and target.read_bytes() == data:
            continue
        save(target, name)
        atomic_write(target, data, path.stat().st_mode & 0o777)
        print("  extras: install %s" % name)
    for name in sorted(previous - files.keys()):
        target = home / name
        if target.exists() or target.is_symlink():
            save(target, name)
            target.unlink()
            print("  extras: remove %s" % name)
    manifest = home / MANIFEST
    if installing:
        atomic_write(manifest, ("\n".join(sorted(files)) + "\n").encode("utf-8"), 0o600)
        print("  extras: enabled (future installs keep this opt-in)")
    elif manifest.exists():
        manifest.unlink()
        print("  extras: disabled")


def main(argv):
    if len(argv) != 4 or argv[1] not in ("install", "remove", "check", "check-remove"):
        print("Usage: _manage_extras.py <install|remove|check|check-remove> <home> <backup>",
              file=sys.stderr)
        return 1
    try:
        manage(argv[1], argv[2], argv[3])
    except (OSError, ValueError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
