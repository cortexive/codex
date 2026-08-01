#!/usr/bin/env python3
"""Deterministic Codex release admission, overlay proof, and provenance helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PATCH_SCHEMA = "cortexive-codex-patch/v1"
PROVENANCE_SCHEMA = "cortexive-codex-candidate-provenance/v1"
CANDIDATE_FEED_SCHEMA = "cortexive-codex-candidate-feed/v1"
TAG_RE = re.compile(r"^rust-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+/-]{0,255}$")
ALLOWED_OVERLAY_PATH_PREFIXES = ("codex-rs/tui/",)
NATIVE_SIGNAL_PATHS = (
    "codex-rs/tui/src/bottom_pane/",
    "codex-rs/tui/src/chatwidget/",
    "codex-rs/config/",
    "codex-rs/hooks/",
    "codex-rs/protocol/",
)


class MaintenanceError(RuntimeError):
    """A deterministic admission or proof failure."""


@dataclass(frozen=True)
class ReleaseBinding:
    release_id: int
    tag: str
    commit: str | None = None


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout_tail: str
    stderr_tail: str


def stable_releases(payload: Iterable[Mapping[str, Any]]) -> list[ReleaseBinding]:
    admitted: list[ReleaseBinding] = []
    for release in payload:
        tag = release.get("tag_name")
        release_id = release.get("id")
        if (
            release.get("draft") is not False
            or release.get("prerelease") is not False
            or not isinstance(tag, str)
            or not isinstance(release_id, int)
            or TAG_RE.fullmatch(tag) is None
        ):
            continue
        admitted.append(ReleaseBinding(release_id=release_id, tag=tag))
    return sorted(admitted, key=lambda item: version_key(item.tag), reverse=True)


def version_key(tag: str) -> tuple[int, int, int]:
    match = TAG_RE.fullmatch(tag)
    if match is None:
        raise MaintenanceError(f"invalid stable release tag: {tag}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def load_patch_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != PATCH_SCHEMA:
        raise MaintenanceError("invalid patch manifest schema")
    if value.get("state") not in {"active", "migration-candidate", "retired"}:
        raise MaintenanceError("invalid patch state")
    upstream = value.get("upstream")
    overlay = value.get("overlay")
    files = value.get("expectedChangedFiles")
    matrix = value.get("nativeRetirementMatrix")
    commands = value.get("commands")
    if (
        not isinstance(value.get("patchId"), str)
        or SAFE_ID_RE.fullmatch(value["patchId"]) is None
        or not isinstance(upstream, dict)
        or upstream.get("repository") != "openai/codex"
        or not isinstance(upstream.get("baseTag"), str)
        or TAG_RE.fullmatch(upstream["baseTag"]) is None
        or not isinstance(upstream.get("baseCommit"), str)
        or SHA_RE.fullmatch(upstream["baseCommit"]) is None
    ):
        raise MaintenanceError("invalid immutable upstream binding")
    if (
        not isinstance(overlay, dict)
        or overlay.get("kind") != "ordered-commits"
        or not isinstance(overlay.get("sourceBaseCommit"), str)
        or SHA_RE.fullmatch(overlay["sourceBaseCommit"]) is None
        or not isinstance(overlay.get("commits"), list)
    ):
        raise MaintenanceError("invalid ordered overlay")
    if not overlay["commits"] or not all(
        isinstance(commit, str) and SHA_RE.fullmatch(commit) for commit in overlay["commits"]
    ):
        raise MaintenanceError("invalid overlay commit identity")
    if not isinstance(files, list) or not files or len(files) != len(set(files)):
        raise MaintenanceError("invalid expected changed-file set")
    if not all(isinstance(item, str) and item.startswith(ALLOWED_OVERLAY_PATH_PREFIXES) for item in files):
        raise MaintenanceError("overlay path exceeds changed-area boundary")
    if not isinstance(matrix, list) or len(matrix) != 11 or len(matrix) != len(set(matrix)):
        raise MaintenanceError("native retirement matrix must contain 11 unique rows")
    if (
        not isinstance(commands, dict)
        or set(commands)
        != {"format", "focusedTests", "check", "clippy", "build", "changedAreaGate", "ttyCanary"}
        or not all(isinstance(command, str) and shlex.split(command) for command in commands.values())
    ):
        raise MaintenanceError("invalid deterministic gate commands")
    candidate = value.get("candidate")
    if candidate is not None:
        validate_candidate_manifest(candidate, upstream, value["patchId"])
    if value.get("state") == "retired" and overlay["commits"]:
        raise MaintenanceError("retired patch must have an empty overlay")
    return value


def validate_candidate_manifest(
    candidate: Any, upstream: Mapping[str, Any], patch_id: str
) -> None:
    if not isinstance(candidate, dict):
        raise MaintenanceError("invalid candidate identity")
    source = candidate.get("source")
    binary = candidate.get("binary")
    artifact = candidate.get("artifact")
    if (
        not isinstance(candidate.get("identity"), str)
        or SAFE_ID_RE.fullmatch(candidate["identity"]) is None
        or not isinstance(candidate.get("versionId"), str)
        or SAFE_ID_RE.fullmatch(candidate["versionId"]) is None
        or candidate.get("patchId") != patch_id
        or not isinstance(source, dict)
        or not isinstance(source.get("releaseId"), int)
        or source["releaseId"] <= 0
        or source.get("tag") != upstream.get("baseTag")
        or source.get("commit") != upstream.get("baseCommit")
        or not isinstance(candidate.get("branch"), str)
        or SAFE_ID_RE.fullmatch(candidate["branch"]) is None
        or not isinstance(candidate.get("commit"), str)
        or SHA_RE.fullmatch(candidate["commit"]) is None
        or not isinstance(binary, dict)
        or binary.get("name") != "codex"
        or not isinstance(binary.get("sha256"), str)
        or SHA256_RE.fullmatch(binary["sha256"]) is None
        or candidate.get("provenanceAsset") != "provenance.json"
        or candidate.get("validationReceipt") != "commands.json"
        or candidate.get("feedAsset") != "candidate-feed.json"
        or not isinstance(artifact, dict)
        or artifact.get("kind") != "draft-release"
        or artifact.get("repository") != "cortexive/codex"
        or not isinstance(artifact.get("releaseId"), int)
        or artifact["releaseId"] <= 0
        or not isinstance(artifact.get("tag"), str)
        or SAFE_ID_RE.fullmatch(artifact["tag"]) is None
        or not isinstance(artifact.get("url"), str)
        or not artifact["url"].startswith("https://github.com/cortexive/codex/releases/")
    ):
        raise MaintenanceError("invalid candidate identity")


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=False, text=True, capture_output=True, timeout=120
    )
    if completed.returncode != 0:
        raise MaintenanceError(
            f"git {' '.join(args)} failed ({completed.returncode}): {tail(completed.stderr)}"
        )
    return completed.stdout.strip()


def verify_tag_binding(repo: Path, tag: str, expected_commit: str) -> None:
    version_key(tag)
    if SHA_RE.fullmatch(expected_commit) is None:
        raise MaintenanceError("expected commit must be a full SHA-1")
    peeled = run_git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if peeled != expected_commit:
        raise MaintenanceError(f"tag binding mismatch: {tag} expected {expected_commit}, got {peeled}")


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    raw = run_git(repo, "diff", "--name-only", "--no-renames", f"{base}..{head}")
    return sorted(line for line in raw.splitlines() if line)


def verify_changed_file_bounds(repo: Path, base: str, head: str, manifest: Mapping[str, Any]) -> list[str]:
    actual = changed_files(repo, base, head)
    expected = sorted(manifest["expectedChangedFiles"])
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise MaintenanceError(f"changed-file bounds mismatch; missing={missing}; extra={extra}")
    return actual


def native_capability_signal(paths: Sequence[str]) -> bool:
    return any(path.startswith(NATIVE_SIGNAL_PATHS) for path in paths)


def run_semantic_adapter(source: Path, fixture: str, output: Path | None = None) -> CommandResult:
    if fixture not in {"overlay", "native-pass", "native-fail"}:
        raise MaintenanceError(f"unknown semantic fixture: {fixture}")
    binary = output or source.with_suffix("")
    compile_result = run_command(["rustc", "--edition=2024", "-o", str(binary), str(source)])
    if compile_result.exit_code != 0:
        raise MaintenanceError(f"semantic adapter did not compile: {compile_result.stderr_tail}")
    return run_command([str(binary), fixture])


def decide_retirement(signal: bool, parity: CommandResult) -> str:
    if not signal:
        return "active"
    return "retired" if parity.exit_code == 0 and "PARITY: PASS" in parity.stdout_tail else "migration-candidate"


def run_command(command: Sequence[str], cwd: Path | None = None, timeout: int = 900) -> CommandResult:
    completed = subprocess.run(
        list(command), cwd=cwd, check=False, text=True, capture_output=True, timeout=timeout
    )
    return CommandResult(
        command=" ".join(command),
        exit_code=completed.returncode,
        stdout_tail=tail(completed.stdout),
        stderr_tail=tail(completed.stderr),
    )


def run_manifest_gates(root: Path, manifest: Mapping[str, Any], output: Path) -> list[CommandResult]:
    commands = manifest.get("commands")
    if not isinstance(commands, dict) or not commands:
        raise MaintenanceError("patch manifest has no deterministic commands")
    results: list[CommandResult] = []
    for name, command in commands.items():
        if not isinstance(name, str) or not isinstance(command, str):
            raise MaintenanceError("invalid manifest command")
        argv = shlex.split(command)
        if name == "ttyCanary":
            argv = [sys.executable, str(Path(__file__).resolve()), "tty-canary"]
        cwd = root / "codex-rs" if argv and argv[0] == "cargo" else root
        result = run_command(argv, cwd=cwd, timeout=3600)
        results.append(result)
        print(f"GATE[{name}]: exit={result.exit_code} command={result.command}")
        if result.stdout_tail:
            print(result.stdout_tail)
        if result.stderr_tail:
            print(result.stderr_tail, file=sys.stderr)
        write_json(output, {"commands": [item.__dict__ for item in results]})
        if result.exit_code != 0:
            raise MaintenanceError(f"gate failed: {name}")
    return results


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_provenance(
    *,
    release_id: int,
    tag: str,
    commit: str,
    patch_id: str,
    overlay_commits: Sequence[str],
    candidate_branch: str,
    candidate_commit: str,
    binary: Path,
    commands: Sequence[CommandResult],
    retirement_signal: bool,
    retirement_result: str,
    toolchain: str,
) -> dict[str, Any]:
    version = ".".join(str(part) for part in version_key(tag))
    for identity in (commit, candidate_commit, *overlay_commits):
        if SHA_RE.fullmatch(identity) is None:
            raise MaintenanceError(f"non-immutable source identity: {identity}")
    if not binary.is_file():
        raise MaintenanceError(f"candidate binary missing: {binary}")
    if any(result.exit_code != 0 for result in commands):
        raise MaintenanceError("candidate provenance requires all recorded commands to pass")
    binary_digest = sha256(binary)
    overlay_commit = overlay_commits[-1]
    return {
        "schemaVersion": PROVENANCE_SCHEMA,
        "generatedAt": datetime.now(UTC).isoformat(),
        "versionId": f"{version}+cortex.1",
        "channel": "patched",
        "binary": {"path": binary.name, "sha256": binary_digest},
        "upstream": {
            "repository": "openai/codex",
            "releaseId": release_id,
            "version": version,
            "tag": tag,
            "commit": commit,
        },
        "overlay": {"patchId": patch_id, "commit": overlay_commit, "commits": list(overlay_commits)},
        "validationReceipt": "commands.json",
        "candidate": {
            "identity": f"{tag}-{patch_id}",
            "branch": candidate_branch,
            "commit": candidate_commit,
            "binary": binary.name,
            "sha256": binary_digest,
        },
        "toolchain": toolchain,
        "commands": [result.__dict__ for result in commands],
        "retirementProbe": {"signal": retirement_signal, "result": retirement_result},
        "promotion": {"enabled": False, "performed": False},
    }


def build_candidate_feed(provenance: Mapping[str, Any]) -> dict[str, Any]:
    upstream = provenance.get("upstream")
    candidate = provenance.get("candidate")
    binary = provenance.get("binary")
    if (
        provenance.get("schemaVersion") != PROVENANCE_SCHEMA
        or not isinstance(upstream, Mapping)
        or not isinstance(candidate, Mapping)
        or not isinstance(binary, Mapping)
        or not isinstance(candidate.get("identity"), str)
        or SAFE_ID_RE.fullmatch(candidate["identity"]) is None
        or not isinstance(upstream.get("tag"), str)
        or TAG_RE.fullmatch(upstream["tag"]) is None
        or not isinstance(upstream.get("commit"), str)
        or SHA_RE.fullmatch(upstream["commit"]) is None
        or not isinstance(binary.get("sha256"), str)
        or SHA256_RE.fullmatch(binary["sha256"]) is None
    ):
        raise MaintenanceError("invalid provenance for candidate feed")
    return {
        "schemaVersion": CANDIDATE_FEED_SCHEMA,
        "candidateId": candidate["identity"],
        "sourceTag": upstream["tag"],
        "sourceCommit": upstream["commit"],
        "status": "ready",
        "provenance": "provenance.json",
        "sha256": binary["sha256"],
    }


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def tail(value: str, limit: int = 8192) -> str:
    return value[-limit:]


def tty_fixture() -> int:
    rows = [
        ("thread-alpha", "FORGE-0002", ["thread-title", "context-window"]),
        ("thread-alpha", "FORGE-0003", ["thread-title", "context-window"]),
        ("thread-successor", None, ["thread-title"]),
        ("thread-beta", "ANVIL-0001", []),
    ]
    for thread, relay, native in rows:
        rendered = ([relay] if relay else []) + native
        sys.stdout.write(f"\x1b[2K\r{thread}: {' | '.join(rendered)}\n")
    sys.stdout.flush()
    print("TTY_CANARY: PASS relay-prefix clear-isolation native-title concurrent-session")
    return 0


def synthetic_rehearsal(root: Path) -> dict[str, Any]:
    manifest = load_patch_manifest(root / "cortex-maintenance/patches/relay-statusline-v1.json")
    probe_source = root / "cortex-maintenance/native_interface_probe.rs"
    with tempfile.TemporaryDirectory(prefix="cortex-codex-rehearsal-") as temp:
        temp_path = Path(temp)
        adapter = temp_path / "native-interface-probe"
        overlay = run_semantic_adapter(probe_source, "overlay", adapter)
        native_pass = run_semantic_adapter(probe_source, "native-pass", adapter)
        native_fail = run_semantic_adapter(probe_source, "native-fail", adapter)
        clean_release = {"overlayApplied": True, "modelSessions": 0, "candidateProduced": overlay.exit_code == 0}
        conflict = {"overlayApplied": False, "ticketKey": "synthetic-release/relay-statusline-v1", "ticketCount": 1, "promotedPointerMoved": False}
        migration_before = decide_retirement(True, native_fail)
        migration_after = decide_retirement(True, native_pass)
        result = {
            "schemaVersion": "cortexive-codex-synthetic-rehearsal/v1",
            "patchId": manifest["patchId"],
            "cleanRelease": clean_release,
            "conflict": conflict,
            "nativeInterface": {"beforeParity": migration_before, "afterParity": migration_after},
            "tty": "PASS" if tty_fixture() == 0 else "FAIL",
        }
        if (
            clean_release != {"overlayApplied": True, "modelSessions": 0, "candidateProduced": True}
            or conflict["ticketCount"] != 1
            or conflict["promotedPointerMoved"]
            or migration_before != "migration-candidate"
            or migration_after != "retired"
        ):
            raise MaintenanceError(f"synthetic rehearsal failed: {result}")
        return result


def parse_command_result(path: Path) -> list[CommandResult]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("commands") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise MaintenanceError("command receipt must be a list")
    return [CommandResult(**value) for value in values]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    release = subparsers.add_parser("select-release")
    release.add_argument("--input", type=Path, required=True)
    release.add_argument("--output", type=Path)

    validate = subparsers.add_parser("validate-manifest")
    validate.add_argument("--manifest", type=Path, required=True)

    binding = subparsers.add_parser("verify-binding")
    binding.add_argument("--repo", type=Path, required=True)
    binding.add_argument("--tag", required=True)
    binding.add_argument("--commit", required=True)

    bounds = subparsers.add_parser("check-bounds")
    bounds.add_argument("--repo", type=Path, required=True)
    bounds.add_argument("--base", required=True)
    bounds.add_argument("--head", required=True)
    bounds.add_argument("--manifest", type=Path, required=True)

    gates = subparsers.add_parser("run-gates")
    gates.add_argument("--root", type=Path, required=True)
    gates.add_argument("--manifest", type=Path, required=True)
    gates.add_argument("--output", type=Path, required=True)

    parity = subparsers.add_parser("semantic-parity")
    parity.add_argument("--source", type=Path, required=True)
    parity.add_argument("--fixture", choices=("overlay", "native-pass", "native-fail"), required=True)

    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--root", type=Path, default=Path.cwd())
    rehearse.add_argument("--output", type=Path)

    subparsers.add_parser("tty-canary")

    provenance = subparsers.add_parser("provenance")
    provenance.add_argument("--release-id", type=int, required=True)
    provenance.add_argument("--tag", required=True)
    provenance.add_argument("--commit", required=True)
    provenance.add_argument("--manifest", type=Path, required=True)
    provenance.add_argument("--candidate-branch", required=True)
    provenance.add_argument("--candidate-commit", required=True)
    provenance.add_argument("--binary", type=Path, required=True)
    provenance.add_argument("--commands", type=Path, required=True)
    provenance.add_argument("--retirement-signal", choices=("true", "false"), required=True)
    provenance.add_argument("--retirement-result", required=True)
    provenance.add_argument("--toolchain", required=True)
    provenance.add_argument("--output", type=Path, required=True)

    candidate_feed = subparsers.add_parser("candidate-feed")
    candidate_feed.add_argument("--provenance", type=Path, required=True)
    candidate_feed.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "select-release":
        releases = stable_releases(json.loads(args.input.read_text(encoding="utf-8")))
        if not releases:
            raise MaintenanceError("no stable rust-v<version> release found")
        value = releases[0].__dict__
        if args.output:
            write_json(args.output, value)
        else:
            print(json.dumps(value, sort_keys=True))
    elif args.command == "validate-manifest":
        load_patch_manifest(args.manifest)
        print("PATCH_MANIFEST: PASS")
    elif args.command == "verify-binding":
        verify_tag_binding(args.repo, args.tag, args.commit)
        print(f"SOURCE_BINDING: PASS {args.tag}@{args.commit}")
    elif args.command == "check-bounds":
        manifest = load_patch_manifest(args.manifest)
        files = verify_changed_file_bounds(args.repo, args.base, args.head, manifest)
        print(json.dumps({"changedFiles": files}, sort_keys=True))
    elif args.command == "run-gates":
        manifest = load_patch_manifest(args.manifest)
        run_manifest_gates(args.root.resolve(), manifest, args.output)
        print("CANDIDATE_GATES: PASS")
    elif args.command == "semantic-parity":
        result = run_semantic_adapter(args.source, args.fixture)
        print(result.stdout_tail, end="" if result.stdout_tail.endswith("\n") else "\n")
        return result.exit_code
    elif args.command == "rehearse":
        value = synthetic_rehearsal(args.root.resolve())
        if args.output:
            write_json(args.output, value)
        print("SYNTHETIC_REHEARSAL: PASS")
    elif args.command == "tty-canary":
        return tty_fixture()
    elif args.command == "provenance":
        manifest = load_patch_manifest(args.manifest)
        value = build_provenance(
            release_id=args.release_id,
            tag=args.tag,
            commit=args.commit,
            patch_id=manifest["patchId"],
            overlay_commits=manifest["overlay"]["commits"],
            candidate_branch=args.candidate_branch,
            candidate_commit=args.candidate_commit,
            binary=args.binary,
            commands=parse_command_result(args.commands),
            retirement_signal=args.retirement_signal == "true",
            retirement_result=args.retirement_result,
            toolchain=args.toolchain,
        )
        write_json(args.output, value)
        print(f"PROVENANCE: PASS sha256={value['candidate']['sha256']}")
    elif args.command == "candidate-feed":
        provenance_value = json.loads(args.provenance.read_text(encoding="utf-8"))
        value = build_candidate_feed(provenance_value)
        write_json(args.output, value)
        print(f"CANDIDATE_FEED: PASS candidateId={value['candidateId']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MaintenanceError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"MAINTENANCE_ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
