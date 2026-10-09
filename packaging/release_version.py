"""Deterministic release versions, including delayed or retried master builds."""
import os
import re
import subprocess
from pathlib import Path

STABLE_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
HEADER = re.compile(r"([a-z][a-z0-9-]*)(?:\([^\n()]+\))?(!)?: .+")


def parse_tag(tag):
    match = STABLE_TAG.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def bump(version, messages):
    level = 2
    for message in messages:
        header = HEADER.fullmatch(message.split("\n", 1)[0])
        if (header and header[2]) or re.search(r"^BREAKING[ -]CHANGE: .+", message, re.MULTILINE):
            level = 0
        elif header and header[1] == "feat":
            level = min(level, 1)
    result = list(version)
    result[level] += 1
    result[level + 1:] = [0] * (2 - level)
    return tuple(result)


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def resolve_version(ref):
    head = git("rev-parse", "HEAD")
    if ref.startswith("refs/tags/"):
        tag = ref.removeprefix("refs/tags/")
        if parse_tag(tag) is None or git("rev-parse", f"{ref}^{{commit}}") != head:
            raise ValueError("A release tag must be vMAJOR.MINOR.PATCH at the checked-out commit")
        return tag[1:]
    history = git("rev-list", "--first-parent", "HEAD").splitlines()
    anchors = []
    for tag in git("tag", "--list", "v*").splitlines():
        version = parse_tag(tag)
        if version is not None:
            commit = git("rev-parse", f"refs/tags/{tag}^{{commit}}")
            if commit in history:
                anchors.append((version, commit))
    if not anchors:
        raise ValueError("No stable vMAJOR.MINOR.PATCH tag on the first-parent history")
    version, anchor = max(anchors)
    previous = anchor
    for commit in reversed(history[:history.index(anchor)]):
        messages = git("log", "--format=%B%x00", f"{previous}..{commit}").split("\0")
        version = bump(version, (message.strip() for message in messages if message.strip()))
        previous = commit
    return ".".join(map(str, version))


if __name__ == "__main__":
    version = resolve_version(os.environ.get("GITHUB_REF", "refs/heads/master"))
    print(version)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"version={version}\ncommit={git('rev-parse', 'HEAD')}\n")
