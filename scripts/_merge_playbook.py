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

Fidelity guarantees: the user's content is preserved byte-for-byte. We never
rstrip whitespace from user lines, we honor the user file's original newline
style (\r\n vs \n), and install-then-remove over a file that had no managed
block is a no-op. The only thing install adds (and remove reverses) is a single
blank-line separator between the user's content and our block.
"""
import os
import sys

BEGIN = "# >>> copilot-review-team (managed — do not edit between markers) >>>"
END = "# <<< copilot-review-team <<<"


def _detect_eol(text):
    """Return the dominant end-of-line style of text: '\\r\\n' or '\\n'.

    A file is treated as CRLF only if it contains at least one \\r\\n and CRLF
    endings are at least as common as bare LF endings. Empty/EOL-free text
    defaults to '\\n'.
    """
    crlf = text.count("\r\n")
    if crlf == 0:
        return "\n"
    lf_only = text.count("\n") - crlf
    return "\r\n" if crlf >= lf_only else "\n"


def _split_managed(text):
    """Split text into (residual_user_text, found_block).

    Removes ALL balanced BEGIN..END blocks. Returns the user-owned residual text
    (with its line endings normalized to bare \\n — callers re-apply the desired
    EOL) and a bool indicating whether at least one block was removed.

    User content is preserved verbatim apart from EOL normalization: trailing
    whitespace on content lines and trailing blank lines are kept. The single
    blank-line separator that install inserts before a block IS consumed here so
    that install-then-remove reverses cleanly.

    Raises ValueError if the markers are unbalanced or out of order (a BEGIN with
    no matching END, or an END seen before its BEGIN).
    """
    # Normalize to bare \n for parsing; preserve everything else exactly.
    norm = text.replace("\r\n", "\n")
    # splitlines() drops a trailing newline; track it so we can restore it.
    had_trailing_nl = norm.endswith("\n")
    lines = norm.split("\n")
    if had_trailing_nl:
        # split() leaves a trailing "" after the final \n; drop it so we operate
        # on actual content lines and re-add the trailing newline at the end.
        lines = lines[:-1]

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
            # Drop the single blank-line separator install inserted before the
            # block, if present, so remove reverses install exactly.
            if out and out[-1] == "":
                out.pop()
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
    if had_trailing_nl and residual != "":
        residual += "\n"
    return residual, found


def _atomic_write(path, content):
    """Write content to path atomically (temp file in same dir + os.replace).

    The temp file is cleaned up if the write or the replace fails, so a failure
    never leaks a `.<name>.tmp-<pid>` file in the user's directory. Newlines are
    written verbatim (newline="") — the caller has already chosen the EOL style.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    tmp = os.path.join(directory, ".%s.tmp-%d" % (os.path.basename(path), os.getpid()))
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read(path):
    """Return file contents, or '' if the file does not exist.

    Read in binary-faithful text mode (newline="") so \\r\\n endings survive into
    the returned string rather than being translated to \\n by the io layer.
    """
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def cmd_install(target, source_file):
    source = _read(source_file)
    # Reject a source that itself contains a marker line: it would corrupt
    # future parsing of the managed block. Compare after stripping per-line.
    for raw in source.replace("\r\n", "\n").split("\n"):
        if raw.strip() in (BEGIN, END):
            sys.stderr.write(
                "error: source content contains a managed-block marker line "
                "(%r) — refusing to install (it would corrupt the block).\n"
                % raw.strip()
            )
            return 1
    source = source.replace("\r\n", "\n").strip("\n")

    existed = os.path.exists(target)
    original = _read(target)
    eol = _detect_eol(original)

    residual, had_block = _split_managed(original)
    # residual is in bare-\n form with its trailing newline (if any) preserved.

    block = BEGIN + "\n" + source + "\n" + END + "\n"
    if residual != "":
        # Ensure the user content ends with a newline before the single blank
        # separator line, then our block.
        if not residual.endswith("\n"):
            residual += "\n"
        new_content = residual + "\n" + block
    else:
        new_content = block

    # Re-apply the user file's original EOL style throughout.
    if eol != "\n":
        new_content = new_content.replace("\n", eol)

    _atomic_write(target, new_content)

    if not existed:
        print("playbook: wrote new copilot-instructions.md with managed block")
    elif had_block:
        print("playbook: upgraded managed block in place (preserved user content)")
    elif residual != "":
        print("playbook: appended managed block (preserved existing user content)")
    else:
        print("playbook: wrote managed block (file had no user content)")
    return 0


def cmd_remove(target):
    if not os.path.exists(target):
        print("playbook: nothing to remove (no copilot-instructions.md)")
        return 0

    original = _read(target)
    eol = _detect_eol(original)
    residual, had_block = _split_managed(original)
    # residual is in bare-\n form, preserving the user's trailing newlines.

    if not had_block:
        print("playbook: no managed block found — left file untouched")
        return 0

    if residual == "":
        os.remove(target)
        print("playbook: removed managed block and deleted now-empty file")
    else:
        if eol != "\n":
            residual = residual.replace("\n", eol)
        _atomic_write(target, residual)
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
