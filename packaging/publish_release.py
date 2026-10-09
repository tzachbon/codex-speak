"""Publish the tested installer without moving tags or replacing completed assets."""
import json
import os
import re
import subprocess
from pathlib import Path

from release_version import parse_tag


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def remote_tags():
    refs = {ref: sha for sha, ref in (line.split() for line in
                                    command("git", "ls-remote", "--tags", "origin").splitlines())}
    return {ref.removeprefix("refs/tags/"): refs.get(ref + "^{}", sha)
            for ref, sha in refs.items() if not ref.endswith("^{}")}


def read_release(repository, tag):
    return json.loads(command("gh", "release", "view", tag, "--repo", repository,
                              "--json", "assets,isDraft"))


def complete_asset(release, name):
    asset = next((asset for asset in release["assets"] if asset["name"] == name), None)
    if asset and (asset["state"] != "uploaded" or asset["size"] <= 0):
        raise ValueError(f"Incomplete {name} asset. Repair the failed upload before rerunning; no asset was overwritten.")
    return asset is not None


def publish(version, commit, repository, artifact):
    tag = f"v{version}"
    if parse_tag(tag) is None or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Invalid release version or commit SHA")
    artifact = Path(artifact)
    if not artifact.is_file() or not artifact.stat().st_size:
        raise ValueError("The tested installer is missing or empty")
    tags = remote_tags()
    if tag not in tags:
        command("gh", "api", "--method", "POST", f"repos/{repository}/git/refs",
                "-f", f"ref=refs/tags/{tag}", "-f", f"sha={commit}")
        tags = remote_tags()
    if tags.get(tag) != commit:
        raise ValueError(f"{tag} does not point to the tested commit {commit}")
    # A failed read may be auth/network related; create fails rather than modifying an existing release.
    existing = subprocess.run(["gh", "release", "view", tag, "--repo", repository,
                               "--json", "assets,isDraft"], capture_output=True, text=True,
                              encoding="utf-8")
    if existing.returncode:
        command("gh", "release", "create", tag, str(artifact), "--repo", repository,
                "--verify-tag", "--draft", "--title", f"Codex Speak {tag}", "--generate-notes")
        release = read_release(repository, tag)
    else:
        release = json.loads(existing.stdout)
    if not complete_asset(release, artifact.name):
        command("gh", "release", "upload", tag, str(artifact), "--repo", repository)
        release = read_release(repository, tag)
        if not complete_asset(release, artifact.name):
            raise ValueError("Installer upload did not complete; release remains unpublished")
    if release["isDraft"]:
        published = command("gh", "api", "--paginate", f"repos/{repository}/releases", "--jq",
                            ".[] | select(.draft == false and .prerelease == false) | .tag_name")
        versions = [value for name in published.splitlines() if (value := parse_tag(name)) is not None]
        latest = "true" if not versions or parse_tag(tag) >= max(versions) else "false"
        command("gh", "release", "edit", tag, "--repo", repository, "--draft=false", f"--latest={latest}")
        if read_release(repository, tag)["isDraft"]:
            raise ValueError("Release is still a draft after publication")
    print(f"Published {tag} at {commit}")


if __name__ == "__main__":
    publish(os.environ["RELEASE_VERSION"], os.environ["RELEASE_COMMIT"],
            os.environ["GITHUB_REPOSITORY"], "dist/CodexSpeak-Setup.exe")
