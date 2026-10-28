#!/usr/bin/env python3
"""Marker-block merge for the review-team playbook.

Used by BOTH install.sh and uninstall.sh to manage this repo's content inside a
user's copilot-instructions.md without clobbering anything they wrote. Our
content lives between two sentinel markers; everything outside the markers is the
user's and is preserved verbatim unless legacy migration is explicitly requested.

CLI:
    _merge_playbook.py check <target_playbook> [--migrate-legacy-playbook]
    _merge_playbook.py install <target_playbook> <source_content_file> [--migrate-legacy-playbook]
    _merge_playbook.py remove  <target_playbook>

install: strip any existing managed block(s), then append a single fresh managed
block holding the source content. Running it twice is idempotent.
Unmarked legacy playbooks block installation unless migration is explicitly
requested. Migration backs up the original before removing recognized sections.
check: validate the target and migration eligibility without writing anything.

remove: strip the managed block(s); delete the file if nothing else remains.

In every mode, unbalanced/hand-edited markers abort safely (nonzero, no writes).
Writes are atomic (temp file in the same dir + os.replace).

Fidelity guarantees: the user's content is preserved byte-for-byte. We never
rstrip whitespace from user lines, we honor the user file's original newline
style (\r\n vs \n), and install-then-remove over a file that had no managed
block is a no-op. The only thing install adds (and remove reverses) is a single
blank-line separator between the user's content and our block. A metadata line
inside the managed block records when that separator supplied a missing final
newline, so removal can restore the original boundary exactly.
"""
import os
import re
import stat
import sys
import tempfile

BEGIN = "# >>> copilot-review-team (managed — do not edit between markers) >>>"
END = "# <<< copilot-review-team <<<"
NO_FINAL_NEWLINE = "<!-- copilot-review-team: preserve missing final newline -->"
LEGACY_HEADINGS = {
    "# Multi-agent team playbook": (
        "## The team",
        "## Default pipeline for non-trivial tasks",
        "## Review-only requests (no developer phase)",
        "## Repo-specific overrides",
    ),
    "# Multi-agent review team playbook": (
        "## The teams",
        "## Match review depth to task size",
        "## Review pipeline",
        "## Repo-specific overrides",
    ),
}


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
    with its original line endings and a bool indicating whether at least one
    block was removed.

    User content is preserved verbatim. The separator and any final newline
    supplied by install are consumed, so install-then-remove reverses cleanly.

    Raises ValueError if the markers are unbalanced or out of order (a BEGIN with
    no matching END, or an END seen before its BEGIN).
    """
    out = []
    found = False
    inside = False
    first_managed_line = False
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if index < len(lines) - 1:
            line += "\n"
        stripped = line.strip()
        if stripped == BEGIN:
            if inside:
                raise ValueError("nested BEGIN marker (missing END before it)")
            inside = True
            first_managed_line = True
            found = True
            # Drop the single blank-line separator install inserted before the
            # block, if present, so remove reverses install exactly.
            if out and out[-1] in ("\n", "\r\n"):
                out.pop()
            continue
        if stripped == END:
            if not inside:
                raise ValueError("END marker before any BEGIN marker")
            inside = False
            continue
        if inside:
            if stripped == NO_FINAL_NEWLINE:
                if not first_managed_line or not out or not out[-1].endswith("\n"):
                    raise ValueError("invalid missing-final-newline metadata")
                ending = "\r\n" if line.endswith("\r\n") else "\n"
                if not out[-1].endswith(ending):
                    raise ValueError("missing-final-newline metadata has incompatible line ending")
                out[-1] = out[-1][:-len(ending)]
            first_managed_line = False
        else:
            out.append(line)
    if inside:
        raise ValueError("BEGIN marker without a matching END marker")

    return "".join(out), found


def _atomic_write(path, content):
    """Write content to path atomically (temp file in same dir + os.replace).

    The temp file is cleaned up if the write or the replace fails, so a failure
    never leaks a `.<name>.tmp-<pid>` file in the user's directory. Newlines are
    written verbatim (newline="") — the caller has already chosen the EOL style.

    If `path` already exists, the temp file's permission bits are set to match
    it before the replace: `open(..., "w")` creates a new file at whatever mode
    the process umask allows, which can silently widen or narrow the original
    file's permissions (e.g. a `0600` instructions file becoming `0644`).
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    tmp = os.path.join(directory, ".%s.tmp-%d" % (os.path.basename(path), os.getpid()))
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        try:
            mode = os.stat(path).st_mode
        except OSError:
            pass  # path doesn't exist yet; keep the temp file's default mode
        else:
            os.chmod(tmp, stat.S_IMODE(mode))
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


def _legacy_ranges(text):
    """Locate whole unmarked playbooks, excluding headings inside code fences."""
    headings = []
    setext_underlines = []
    fence = None
    offset = 0
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.rstrip("\r")
        match = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", stripped)
        if fence:
            if (
                match and match[1][0] == fence[0]
                and len(match[1]) >= len(fence) and not match[2].strip()
            ):
                fence = None
        elif match:
            fence = match[1]
        else:
            heading = re.fullmatch(r" {0,3}#(?:[ \t]+(.*))?", stripped)
            if heading:
                title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", heading[1] or "").strip(" \t")
                headings.append((offset, number, "# " + title))
            elif re.fullmatch(r" {0,3}=+[ \t]*", stripped):
                setext_underlines.append(offset)
        offset += len(line) + 1
    if fence and any(heading in LEGACY_HEADINGS for _, _, heading in headings):
        raise ValueError(
            "unterminated code fence in legacy playbook; cannot bound migration safely"
        )
    ranges = []
    for index, (start, number, heading) in enumerate(headings):
        if heading in LEGACY_HEADINGS:
            end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
            if any(start < offset < end for offset in setext_underlines):
                raise ValueError(
                    "possible Setext H1 boundary in legacy playbook; "
                    "refusing automatic migration. Back up and edit obsolete routing manually"
                )
            ranges.append((start, end, number, heading))
    return ranges


def _prepare_target(original, migrate_legacy=False):
    residual, had_block = _split_managed(original)
    ranges = _legacy_ranges(residual)
    if ranges and not migrate_legacy:
        lines = ", ".join(str(item[2]) for item in ranges)
        raise ValueError(
            "unmarked legacy playbook outside managed markers at residual line(s) %s; "
            "review the section, then rerun install.sh with --migrate-legacy-playbook "
            "to back up and remove it, or remove it manually" % lines
        )
    for start, end, _, heading in ranges:
        section = residual[start:end]
        lines = {line.strip() for line in section.split("\n")}
        if not all(item in lines for item in LEGACY_HEADINGS[heading]) or not all(
            name in section for name in (
                "local-code-reviewer", "local-critical-reviewer",
                "local-deep-reviewer", "local-integration-reviewer",
            )
        ):
            raise ValueError(
                "unrecognized legacy playbook structure; refusing automatic migration. "
                "Back up and remove obsolete routing manually"
            )
    for start, end, _, _ in reversed(ranges):
        residual = residual[:start] + residual[end:]
    return residual, had_block, bool(ranges)


def cmd_install(target, source_file, migrate_legacy=False):
    source = _read(source_file)
    # Reject a source that itself contains a marker line: it would corrupt
    # future parsing of the managed block. Compare after stripping per-line.
    for raw in source.replace("\r\n", "\n").split("\n"):
        if raw.strip() in (BEGIN, END, NO_FINAL_NEWLINE):
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

    residual, had_block, migrated = _prepare_target(original, migrate_legacy)
    missing_final_newline = bool(residual) and not residual.endswith("\n")
    metadata = NO_FINAL_NEWLINE + "\n" if missing_final_newline else ""
    block = (BEGIN + "\n" + metadata + source + "\n" + END + "\n").replace("\n", eol)
    separator = ""
    if residual:
        separator = eol * (2 if missing_final_newline else 1)
    new_content = residual + separator + block

    if migrated:
        descriptor, backup = tempfile.mkstemp(
            prefix=os.path.basename(target) + ".legacy-",
            suffix=".bak", dir=os.path.dirname(os.path.abspath(target)),
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(original)
        os.chmod(backup, stat.S_IMODE(os.stat(target).st_mode))
        print("playbook: legacy original backed up to %s" % backup)
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
    residual, had_block = _split_managed(original)

    if not had_block:
        print("playbook: no managed block found — left file untouched")
        return 0

    if residual == "":
        os.remove(target)
        print("playbook: removed managed block and deleted now-empty file")
    else:
        _atomic_write(target, residual)
        print("playbook: removed managed block (preserved user content)")
    return 0


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("usage: _merge_playbook.py check|install|remove ...\n")
        return 2
    mode = argv[1]
    try:
        if mode in ("check", "install"):
            arguments = argv[2:]
            migrate_legacy = bool(arguments and arguments[-1] == "--migrate-legacy-playbook")
            if migrate_legacy:
                arguments = arguments[:-1]
            if len(arguments) != (2 if mode == "install" else 1):
                sys.stderr.write(
                    "usage: _merge_playbook.py check <target> [--migrate-legacy-playbook]\n"
                    "   or: _merge_playbook.py install <target> <source_file> [--migrate-legacy-playbook]\n"
                )
                return 2
            if mode == "check":
                _prepare_target(_read(arguments[0]), migrate_legacy)
                return 0
            return cmd_install(arguments[0], arguments[1], migrate_legacy)
        if mode == "remove":
            if len(argv) != 3:
                sys.stderr.write("usage: _merge_playbook.py remove <target>\n")
                return 2
            return cmd_remove(argv[2])
    except ValueError as exc:
        sys.stderr.write(
            "error: %s in %s — refusing to touch the file. "
            "Review the reported issue before re-running.\n" % (exc, argv[2])
        )
        return 1
    sys.stderr.write("error: unknown mode %r (expected check|install|remove)\n" % mode)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
