"""No-network checks for bundled-source integrity and opt-in data retrieval."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import fetch_optional_data
import project_paths
import verify_upstream_snapshot

ROOT = Path(__file__).resolve().parents[1]


class SnapshotToolsTest(unittest.TestCase):
    def test_included_snapshot_has_expected_scope(self):
        manifest = json.loads((ROOT / "UPSTREAM_MANIFEST.json").read_text())
        self.assertEqual(len(manifest["files"]), 224)
        self.assertEqual(sum(item["included"] for item in manifest["files"]), 212)
        self.assertEqual(sum(not item["included"] for item in manifest["files"]), 12)
        self.assertEqual(manifest["byte_identical_files"], 211)
        self.assertEqual(manifest["sanitized_files"], ["README.md"])

    def test_all_included_snapshot_hashes_verify_without_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), redirect_stdout(io.StringIO()):
            verify_upstream_snapshot.main()

    def test_default_data_command_is_list_only_and_no_network(self):
        output = io.StringIO()
        with patch("sys.argv", ["fetch_optional_data.py"]), patch.object(fetch_optional_data, "urlopen", side_effect=AssertionError("network forbidden")), redirect_stdout(output):
            fetch_optional_data.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result["action"], "list_only_no_network")
        self.assertEqual(len(result["files"]), 12)

    def test_data_selection_without_two_explicit_flags_never_connects(self):
        path = "data/evaluation/tasks.jsonl"
        for args in (["--select", path], ["--select", path, "--allow-network"],
                     ["--select", path, "--acknowledge-third-party-data"]):
            with self.subTest(args=args), patch("sys.argv", ["fetch_optional_data.py", *args]), patch.object(fetch_optional_data, "urlopen", side_effect=AssertionError("network forbidden")), redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                fetch_optional_data.main()

    def test_wrong_length_and_git_blob_are_rejected(self):
        with self.assertRaises(ValueError):
            fetch_optional_data.validate_bytes(b"x", {"source_bytes": 2, "source_git_blob_sha1": "0"*40})
        with self.assertRaises(ValueError):
            fetch_optional_data.validate_bytes(b"x", {"source_bytes": 1, "source_git_blob_sha1": "0"*40})

    def test_default_source_is_bundled_reference(self):
        self.assertEqual(project_paths.upstream_path(), ROOT / "upstream_reference")

    def test_no_active_root_ci_or_git_submodule_is_bundled(self):
        self.assertFalse((ROOT / ".github/workflows").exists())
        self.assertFalse((ROOT / "upstream_reference/.gitmodules").exists())
        self.assertTrue(all(item["mode"] in {"100644", "100755"} for item in json.loads((ROOT / "UPSTREAM_MANIFEST.json").read_text())["files"]))


if __name__ == "__main__":
    unittest.main()
