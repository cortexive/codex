from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("cortex_upstream_maintenance.py")
SPEC = importlib.util.spec_from_file_location("cortex_upstream_maintenance", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
maintenance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = maintenance
SPEC.loader.exec_module(maintenance)


class ReleaseSelectionTest(unittest.TestCase):
    def test_filters_draft_prerelease_and_non_rust_tags_and_sorts_semver(self) -> None:
        payload = [
            {"id": 1, "tag_name": "rust-v0.99.0", "draft": False, "prerelease": False},
            {"id": 2, "tag_name": "rust-v0.146.0", "draft": False, "prerelease": False},
            {"id": 3, "tag_name": "rust-v0.147.0-alpha.1", "draft": False, "prerelease": True},
            {"id": 4, "tag_name": "v9.0.0", "draft": False, "prerelease": False},
            {"id": 5, "tag_name": "rust-v1.0.0", "draft": True, "prerelease": False},
        ]
        self.assertEqual([item.tag for item in maintenance.stable_releases(payload)], ["rust-v0.146.0", "rust-v0.99.0"])


class GitBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.email", "test@example.invalid"], check=True)
        (self.repo / "base").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", self.repo, "add", "base"], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-qm", "base"], check=True)
        self.base = self.git("rev-parse", "HEAD")
        subprocess.run(["git", "-C", self.repo, "tag", "rust-v0.146.0"], check=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", "-C", self.repo, *args], text=True).strip()

    def test_verifies_peeled_tag_commit(self) -> None:
        maintenance.verify_tag_binding(self.repo, "rust-v0.146.0", self.base)
        with self.assertRaisesRegex(maintenance.MaintenanceError, "tag binding mismatch"):
            maintenance.verify_tag_binding(self.repo, "rust-v0.146.0", "f" * 40)

    def test_enforces_exact_changed_file_set(self) -> None:
        changed = "codex-rs/tui/src/cortex_statusline.rs"
        (self.repo / changed).parent.mkdir(parents=True)
        (self.repo / changed).write_text("overlay\n", encoding="utf-8")
        subprocess.run(["git", "-C", self.repo, "add", changed], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-qm", "overlay"], check=True)
        head = self.git("rev-parse", "HEAD")
        manifest = {"expectedChangedFiles": [changed]}
        self.assertEqual(maintenance.verify_changed_file_bounds(self.repo, self.base, head, manifest), [changed])
        with self.assertRaisesRegex(maintenance.MaintenanceError, "changed-file bounds mismatch"):
            maintenance.verify_changed_file_bounds(
                self.repo, self.base, head, {"expectedChangedFiles": [changed, "codex-rs/tui/src/lib.rs"]}
            )


class ManifestAndRetirementTest(unittest.TestCase):
    def test_repository_manifest_is_valid_and_active(self) -> None:
        root = MODULE_PATH.parents[2]
        manifest = maintenance.load_patch_manifest(root / "cortex-maintenance/patches/relay-statusline-v1.json")
        self.assertEqual(manifest["state"], "active")
        self.assertEqual(manifest["upstream"]["baseTag"], "rust-v0.146.0")
        self.assertEqual(
            manifest["overlay"]["sourceBaseCommit"],
            "6751b54cae32b23786001e2414d749a9916201e1",
        )
        self.assertEqual(manifest["candidate"]["feedAsset"], "candidate-feed.json")
        self.assertEqual(manifest["candidate"]["artifact"]["releaseId"], 363589438)
        self.assertEqual(len(manifest["nativeRetirementMatrix"]), 11)

    def test_signal_never_retires_without_full_compiled_parity(self) -> None:
        self.assertTrue(maintenance.native_capability_signal(["codex-rs/tui/src/bottom_pane/new_api.rs"]))
        failed = maintenance.CommandResult("probe", 1, "PARITY: FAIL", "")
        passed = maintenance.CommandResult("probe", 0, "PARITY: PASS rows=11", "")
        self.assertEqual(maintenance.decide_retirement(True, failed), "migration-candidate")
        self.assertEqual(maintenance.decide_retirement(False, passed), "active")
        self.assertEqual(maintenance.decide_retirement(True, passed), "retired")

    def test_compiled_adapter_exercises_pass_and_fail_fixtures(self) -> None:
        root = MODULE_PATH.parents[2]
        source = root / "cortex-maintenance/native_interface_probe.rs"
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "probe"
            passed = maintenance.run_semantic_adapter(source, "native-pass", binary)
            failed = maintenance.run_semantic_adapter(source, "native-fail", binary)
        self.assertEqual(passed.exit_code, 0)
        self.assertIn("rows=11", passed.stdout_tail)
        self.assertNotEqual(failed.exit_code, 0)


class ProvenanceAndRehearsalTest(unittest.TestCase):
    def test_provenance_binds_digest_sources_commands_and_no_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "codex"
            binary.write_bytes(b"candidate")
            value = maintenance.build_provenance(
                release_id=361463950,
                tag="rust-v0.146.0",
                commit="a" * 40,
                patch_id="relay-statusline-v1",
                overlay_commits=["b" * 40],
                candidate_branch="cortexive/candidate/rust-v0.146.0-relay-statusline-v1",
                candidate_commit="c" * 40,
                binary=binary,
                commands=[maintenance.CommandResult("cargo check", 0, "ok", "")],
                retirement_signal=False,
                retirement_result="active",
                toolchain="rustc test",
            )
        self.assertEqual(value["candidate"]["sha256"], maintenance.hashlib.sha256(b"candidate").hexdigest())
        self.assertFalse(value["promotion"]["enabled"])
        self.assertFalse(value["promotion"]["performed"])
        feed = maintenance.build_candidate_feed(value)
        self.assertEqual(feed["schemaVersion"], "cortexive-codex-candidate-feed/v1")
        self.assertEqual(feed["candidateId"], "rust-v0.146.0-relay-statusline-v1")
        self.assertEqual(feed["sourceCommit"], "a" * 40)
        self.assertEqual(feed["sha256"], maintenance.hashlib.sha256(b"candidate").hexdigest())

    def test_synthetic_clean_conflict_and_native_rehearsal(self) -> None:
        root = MODULE_PATH.parents[2]
        receipt = maintenance.synthetic_rehearsal(root)
        self.assertEqual(receipt["cleanRelease"]["modelSessions"], 0)
        self.assertEqual(receipt["conflict"]["ticketCount"], 1)
        self.assertFalse(receipt["conflict"]["promotedPointerMoved"])
        self.assertEqual(receipt["nativeInterface"]["beforeParity"], "migration-candidate")
        self.assertEqual(receipt["nativeInterface"]["afterParity"], "retired")


if __name__ == "__main__":
    unittest.main()
