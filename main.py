#!/usr/bin/env python3
"""
main.py

Assumes the current working directory (pwd) is a git repo folder.
Fetches all remotes, then prints the latest commit on each remote branch,
and then prints ONLY local branches that do NOT correspond to any remote branch.

Output is formatted neatly for terminal width using a custom "piece" wrapper.
Uses termcolor for coloration.

Requirements:
  pip install termcolor

Usage:
  python main.py [--timestamp-format {readable,iso}]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Iterable

from termcolor import colored


@dataclass(frozen=True)
class BranchInfo:
    kind: str             # "remote" or "local"
    display_name: str     # e.g. origin/main or main
    refname: str          # full ref
    commit_hash: str
    committer: str
    commit_date: datetime # ISO 8601 parsed
    subject: str


def run_git(repo_dir: Path, args: List[str]) -> str:
    cmd = ["git", "-C", str(repo_dir), *args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"Git command failed:\n  {' '.join(cmd)}\n\nSTDOUT:\n{p.stdout}\n\nSTDERR:\n{p.stderr}"
        )
    return p.stdout


def ensure_git_repo(repo_dir: Path) -> None:
    try:
        out = run_git(repo_dir, ["rev-parse", "--is-inside-work-tree"]).strip()
    except Exception:
        raise SystemExit("Not a git repository (or git not available).")
    if out != "true":
        raise SystemExit("Not inside a git work tree.")


def fetch_all_remotes(repo_dir: Path) -> None:
    # Fetch all remotes and prune deleted branches
    run_git(repo_dir, ["fetch", "--all", "--prune", "--tags"])


def list_remote_branches(repo_dir: Path) -> List[Tuple[str, str]]:
    """
    Returns list of (full_refname, short_name) for remote branches
    e.g. ("refs/remotes/origin/main", "origin/main")
    """
    stdout = run_git(repo_dir, ["for-each-ref", "--format=%(refname:short)", "refs/remotes"])
    shorts = [line.strip() for line in stdout.splitlines() if line.strip()]
    shorts = [s for s in shorts if not s.endswith("/HEAD")]
    return [(f"refs/remotes/{s}", s) for s in shorts]


def list_local_branches(repo_dir: Path) -> List[Tuple[str, str]]:
    """
    Returns list of (full_refname, short_name) for local branches
    e.g. ("refs/heads/main", "main")
    """
    stdout = run_git(repo_dir, ["for-each-ref", "--format=%(refname:short)", "refs/heads"])
    shorts = [line.strip() for line in stdout.splitlines() if line.strip()]
    return [(f"refs/heads/{s}", s) for s in shorts]


def get_latest_commit(repo_dir: Path, refname: str) -> Tuple[str, str, datetime, str]:
    """
    Returns (hash, committer, date_datetime, subject) for the tip commit of ref.
    Merge commits are included automatically if they are the tip.
    """
    fmt = "%H%x00%cn%x00%cd%x00%s"
    stdout = run_git(repo_dir, ["log", "-1", f"--format={fmt}", "--date=iso-strict", refname]).rstrip("\n")
    parts = stdout.split("\x00")
    if len(parts) != 4:
        raise RuntimeError(f"Unexpected log format for {refname}: {stdout!r}")
    date_obj = datetime.fromisoformat(parts[2])
    return parts[0], parts[1], date_obj, parts[3]


# ----------------------------
# Terminal formatting helpers
# ----------------------------

def term_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size(fallback=(default, 24)).columns
    except Exception:
        return default


def strip_ansi_len(s: str) -> int:
    """
    Best-effort visible length. termcolor uses ANSI escapes.
    We'll approximate by removing ESC sequences.
    """
    import re
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    return len(ansi_re.sub("", s))


def wrap_pieces(
    pieces: Iterable[str],
    *,
    width: int,
    first_prefix: str = "",
    next_prefix: str = "",
) -> List[str]:
    """
    "Piece-aware" wrapper:
      - takes sequential pieces and appends them to a line
      - if the next piece would exceed width, it starts a new line
    This is more readable than plain word-wrap because it respects your logical chunks.

    pieces should already include any spaces they need (e.g. "  " or " | ").
    """
    lines: List[str] = []
    cur = first_prefix

    for piece in pieces:
        if not piece:
            continue

        # If the piece itself is longer than width, just force it onto a new line.
        # (We won't hard-wrap inside the piece; that’s intentional.)
        proposed = cur + piece
        if strip_ansi_len(proposed) <= width or strip_ansi_len(cur) <= strip_ansi_len(first_prefix):
            cur = proposed
            continue

        # Start a new line
        lines.append(cur.rstrip())
        cur = next_prefix + piece.lstrip()

        # If still too long, keep as-is (no internal wrapping).
        if strip_ansi_len(cur) > width:
            lines.append(cur.rstrip())
            cur = next_prefix

    if cur.strip():
        lines.append(cur.rstrip())

    return lines


def format_date(dt: datetime) -> str:
    month = dt.strftime('%b').capitalize() + '.'
    day = dt.day
    ordinal = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    day_str = f"{day}{ordinal}"
    year = dt.year
    time_str = dt.strftime('%I:%M:%S %p')
    offset = dt.utcoffset()
    if offset is not None:
        hours = int(offset.total_seconds() / 3600)
        tz_str = f"GMT{hours:+d}"
    else:
        tz_str = 'GMT'
    return f"{month} {day_str}, {year}, {time_str}, {tz_str}"


def print_block(lines: List[str]) -> None:
    for ln in lines:
        print(ln)


# ----------------------------
# Main output logic
# ----------------------------

def build_branch_info(repo_dir: Path, kind: str, refname: str, display: str) -> BranchInfo:
    h, c, d, s = get_latest_commit(repo_dir, refname)
    return BranchInfo(kind=kind, display_name=display, refname=refname, commit_hash=h, committer=c, commit_date=d, subject=s)


def local_branches_not_on_any_remote(local_shorts: List[str], remote_shorts: List[str]) -> List[str]:
    """
    Exclude local branches that "correspond" to a remote branch.
    We treat local 'foo' as corresponding if any remote branch ends with '/foo'
    (e.g. origin/foo, upstream/foo).
    """
    remote_leaf_names = {r.split("/", 1)[1] for r in remote_shorts if "/" in r}
    return [l for l in local_shorts if l not in remote_leaf_names]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate branch report")
    parser.add_argument('--timestamp-format', choices=['readable', 'iso'], default='readable',
                        help='Format for timestamps: readable (default) or iso')
    args = parser.parse_args()

    repo_dir = Path.cwd()
    ensure_git_repo(repo_dir)

    # Fetch updates
    try:
        fetch_all_remotes(repo_dir)
    except RuntimeError as e:
        print(colored("Error fetching remotes:", "red"), str(e), file=sys.stderr)
        return 2

    width = term_width()

    # Collect branches
    remote_refs = list_remote_branches(repo_dir)
    local_refs = list_local_branches(repo_dir)

    remote_infos: List[BranchInfo] = []
    for full_ref, short in remote_refs:
        try:
            remote_infos.append(build_branch_info(repo_dir, "remote", full_ref, short))
        except RuntimeError:
            continue

    # Local-only: those not corresponding to any remote branch name
    remote_shorts = [short for _, short in remote_refs]
    local_only_short_names = set(local_branches_not_on_any_remote([short for _, short in local_refs], remote_shorts))

    local_only_infos: List[BranchInfo] = []
    for full_ref, short in local_refs:
        if short not in local_only_short_names:
            continue
        try:
            local_only_infos.append(build_branch_info(repo_dir, "local", full_ref, short))
        except RuntimeError:
            continue

    # Sort by date desc (ISO sorts lexicographically)
    remote_infos.sort(key=lambda b: b.commit_date, reverse=True)
    local_only_infos.sort(key=lambda b: b.commit_date, reverse=True)

    # Header
    title = f"Latest commits per branch in {repo_dir.name}"
    print(colored(title, "cyan", attrs=["bold"]))
    print(colored("-" * min(width, max(10, len(title))), "cyan"))
    print()

    def print_section(label: str, infos: List[BranchInfo]) -> None:
        print(colored(label, "cyan", attrs=["bold"]))
        if not infos:
            print(colored("  (none)", "yellow"))
            print()
            return

        for b in infos:
            branch = colored(b.display_name, "green", attrs=["bold"])
            chash = colored(b.commit_hash[:12], "yellow")
            if args.timestamp_format == 'iso':
                cdate = colored(b.commit_date.isoformat(), "magenta")
            else:
                cdate = colored(format_date(b.commit_date), "magenta")
            comm = colored(b.committer, "blue")
            msg = colored(b.subject, "white")

            # Compose into "pieces" so the wrapper can break at sensible boundaries.
            pieces = [
                branch,
                "  ",
                chash,
                "  ",
                cdate,
                "  ",
                comm,
                "  ",
                msg,
            ]

            # Indent subsequent lines for readability
            lines = wrap_pieces(pieces, width=width, first_prefix="  ", next_prefix="    ")
            print_block(lines)

        print()

    print_section("Remote branches", remote_infos)
    print_section("Local branches (no corresponding remote)", local_only_infos)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())