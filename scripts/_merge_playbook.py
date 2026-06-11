#!/usr/bin/env python3
"""Marker-block merge for the review-team playbook.

Used by BOTH install.sh and uninstall.sh to manage this repo's content inside a
user's copilot-instructions.md without clobbering anything they wrote. Our
content lives between two sentinel markers; everything outside the markers is the
user's and is preserved verbatim.

CLI:
    _merge_playbook.py install <target_playbook> <source_content_file>
    _merge_playbook.py remove  <target_playbook>

install: strip any existing managed block(s), then append a single fresh managed
block holding the source content. Running it twice is idempotent.

remove: strip the managed block(s); delete the file if nothing else remains.

In every mode, unbalanced/hand-edited markers abort safely (nonzero, no writes).
Writes are atomic (temp file in the same dir + os.replace).
"""
import os
import sys

BEGIN = "# >>> copilot-review-team (managed — do not edit between markers) >>>"
END = "# <<< copilot-review-team <<<"


def _split_managed(text):
    """Split text into (residual_user_text, found_block).

    Removes ALL balanced BEGIN..END blocks (and the blank line that separated a
    block from preceding content, collapsing cleanly). Returns the user-owned
    residual text and a bool indicating whether at least one block was removed.

    Raises ValueError if the markers are unbalanced or out of order (a BEGIN with
    no matching END, or an END seen before its BEGIN).
    """
    lines = text.splitlines()
    out = []
    found = False
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == BEGIN:
            if inside:
                raise ValueError("nested BEGIN marker (missing END before it)")
            inside = True
            found = True
            continue
        if stripped == END:
            if not inside:
                raise ValueError("END marker before any BEGIN marker")
            inside = False
            continue
        if not inside:
            out.append(line)
    if inside:
        raise ValueError("BEGIN marker without a matching END marker")
    residual = "\n".join(out)
    return residual, found


def _trim_trailing_blank(text):
    """Drop trailing blank/whitespace-only lines, returning '' for all-blank."""
    return text.rstrip("\n").rstrip()


def _atomic_write(path, content):
    """Write content to path atomically (temp file in same dir + os.replace)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    tmp = os.path.join(directory, ".%s.tmp-%d" % (os.path.basename(path), os.getpid()))
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp, path)


def _read(path):
    """Return file contents, or '' if the file does not exist."""
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def cmd_install(target, source_file):
    source = _read(source_file).strip("\n")
    existed = os.path.exists(target)
    original = _read(target)

    residual, had_block = _split_managed(original)
    residual = _trim_trailing_blank(residual)

    block = BEGIN + "\n" + source + "\n" + END + "\n"
    if residual:
        new_content = residual + "\n\n" + block
    else:
        new_content = block

    _atomic_write(target, new_content)

    if not existed:
        print("playbook: wrote new copilot-instructions.md with managed block")
    elif had_block:
        print("playbook: upgraded managed block in place (preserved user content)")
    elif residual:
        print("playbook: appended managed block (preserved existing user content)")
    else:
        print("playbook: wrote managed block (file had no user content)")
    return 0


def cmd_remove(target):
    if not os.path.exists(target):
        print("playbook: nothing to remove (no copilot-instructions.md)")
        return 0

    original = _read(target)
    residual, had_block = _split_managed(original)
    residual = _trim_trailing_blank(residual)

    if not had_block:
        print("playbook: no managed block found — left file untouched")
        return 0

    if residual == "":
        os.remove(target)
        print("playbook: removed managed block and deleted now-empty file")
    else:
        _atomic_write(target, residual + "\n")
        print("playbook: removed managed block (preserved user content)")
    return 0


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("usage: _merge_playbook.py install|remove ...\n")
        return 2
    mode = argv[1]
    try:
        if mode == "install":
            if len(argv) != 4:
                sys.stderr.write(
                    "usage: _merge_playbook.py install <target> <source_file>\n"
                )
                return 2
            return cmd_install(argv[2], argv[3])
        if mode == "remove":
            if len(argv) != 3:
                sys.stderr.write("usage: _merge_playbook.py remove <target>\n")
                return 2
            return cmd_remove(argv[2])
    except ValueError as exc:
        sys.stderr.write(
            "error: %s in %s — refusing to touch the file. "
            "Fix the markers by hand and re-run.\n" % (exc, argv[2])
        )
        return 1
    sys.stderr.write("error: unknown mode %r (expected install|remove)\n" % mode)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
