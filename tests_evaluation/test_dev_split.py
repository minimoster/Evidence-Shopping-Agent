"""Offline development-split tests using explicitly synthetic fixtures only.

No production task source, Final-200 task file, queries, or labels are read.
The synthetic exclusion IDs (10000..10199) are not the real final task IDs.
"""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluation import dev_split


class DevelopmentSplitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "data/grpo/validation.jsonl"
        self.final = self.root / dev_split.BLIND_IDS_KEY
        self.provenance = self.root / "SYNTHETIC_UPSTREAM_MANIFEST.json"
        self.source.parent.mkdir(parents=True)
        self.final.parent.mkdir(parents=True)
        self.source.write_bytes(dev_split.task_ids_jsonl(list(range(100))))
        self.final.write_text(json.dumps({"schema_version": dev_split.BLIND_IDS_SCHEMA, "task_ids": list(range(10000, 10200))}), encoding="utf-8")
        self.pin_synthetic_inputs()

    def pin_synthetic_inputs(self):
        entries = []
        for path, key in ((self.source, "data/grpo/validation.jsonl"), (self.final, dev_split.BLIND_IDS_KEY)):
            data = path.read_bytes()
            entries.append({"path": key, "source_bytes": len(data), "source_git_blob_sha1": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(), "published_sha256": hashlib.sha256(data).hexdigest(), "modified": False})
        self.provenance.write_text(json.dumps({"repository": "synthetic/test-fixtures", "source_commit": "a" * 40, "files": entries}), encoding="utf-8")

    def select(self, **kwargs):
        params = {"source_relative_path": "data/grpo/validation.jsonl", "provenance_manifest_path": self.provenance}
        params.update(kwargs)
        return dev_split.select_development_split(self.source, self.final, **params)

    def test_exactly_twenty_unique_disjoint_ids_and_auditable_hashes(self):
        result = self.select()
        ids = result["task_ids"]
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(set(ids)), 20)
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(set(ids).issubset(set(range(100))))
        self.assertFalse(set(ids).intersection(range(10000, 10200)))
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(result["source"]["commit"], "a" * 40)
        self.assertEqual(result["final_exclusion"]["sha256"], hashlib.sha256(self.final.read_bytes()).hexdigest())
        self.assertEqual(result["source"]["provenance_manifest_sha256"], hashlib.sha256(self.provenance.read_bytes()).hexdigest())
        self.assertEqual(result["source"]["task_count"], 100)
        self.assertEqual(result["final_exclusion"]["source_overlap_count"], 0)
        self.assertFalse(result["evaluated"])

    def test_determinism_seed_changes_and_source_row_order_independence(self):
        first = self.select(seed=123)
        self.assertEqual(first, self.select(seed=123))
        self.assertNotEqual(first["task_ids"], self.select(seed=124)["task_ids"])
        self.source.write_bytes(dev_split.task_ids_jsonl(list(reversed(range(100)))))
        self.pin_synthetic_inputs()
        reordered = self.select(seed=123)
        self.assertEqual(first["task_ids"], reordered["task_ids"])
        self.assertNotEqual(first["source"]["sha256"], reordered["source"]["sha256"])

    def test_selection_algorithm_known_synthetic_vector(self):
        # Compute independently, so the rank domain and seed encoding are pinned.
        expected = sorted(sorted(range(100), key=lambda task_id: (hashlib.sha256(f"shopping-development-split-v1\0{123}\0{task_id}".encode("ascii")).hexdigest(), task_id))[:20])
        self.assertEqual(self.select(seed=123)["task_ids"], expected)

    def test_missing_final_manifest_fails_before_reading_source(self):
        self.final.unlink()
        with patch.object(dev_split, "_read_bytes", wraps=dev_split._read_bytes) as reader:
            with self.assertRaisesRegex(dev_split.SplitError, "Final-200 IDs manifest unavailable"):
                self.select()
        self.assertNotIn(self.source, [call.args[0] for call in reader.call_args_list])

    def test_explicit_final_manifest_is_required(self):
        with self.assertRaisesRegex(dev_split.SplitError, "explicit Final-200"):
            dev_split.select_development_split(self.source, None, source_relative_path="data/grpo/validation.jsonl", provenance_manifest_path=self.provenance)

    def test_incomplete_duplicate_invalid_and_wrong_schema_guard_fail(self):
        variants = [
            {"schema_version": dev_split.BLIND_IDS_SCHEMA, "task_ids": []},
            {"schema_version": dev_split.BLIND_IDS_SCHEMA, "task_ids": list(range(199))},
            {"schema_version": dev_split.BLIND_IDS_SCHEMA, "task_ids": [10000] * 200},
            {"schema_version": dev_split.BLIND_IDS_SCHEMA, "task_ids": [True] + list(range(199))},
            {"schema_version": "unknown", "task_ids": list(range(200))},
            {"schema_version": dev_split.BLIND_IDS_SCHEMA, "task_ids": list(range(200)), "gold": "synthetic-secret"},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                self.final.write_text(json.dumps(variant), encoding="utf-8")
                self.pin_synthetic_inputs()
                with self.assertRaises(dev_split.SplitError):
                    self.select()

    def test_any_source_overlap_fails_instead_of_silently_filtering(self):
        self.source.write_bytes(dev_split.task_ids_jsonl(list(range(100)) + [10000]))
        self.pin_synthetic_inputs()
        with self.assertRaisesRegex(dev_split.SplitError, "excluded Final-200"):
            self.select()

    def test_duplicate_ids_fail_even_if_pool_would_remain_large_enough(self):
        self.source.write_bytes(dev_split.task_ids_jsonl(list(range(100)) + [99]))
        self.pin_synthetic_inputs()
        with self.assertRaisesRegex(dev_split.SplitError, "duplicate task_id"):
            self.select()

    def test_insufficient_pool_fails(self):
        self.source.write_bytes(dev_split.task_ids_jsonl(list(range(19))))
        self.pin_synthetic_inputs()
        with self.assertRaisesRegex(dev_split.SplitError, "insufficient development pool"):
            self.select()

    def test_invalid_json_ids_or_non_id_fields_fail_without_echoing_content(self):
        variants = ['not-json-secret', '[]', '{}', '{"task_id":true}', '{"task_id":1.9}', '{"task_id":"2"}', '{"task_id":-1}', '{"task_id":null}', '{"task_id":1,"gold":"synthetic-secret"}']
        for value in variants:
            with self.subTest(value=value):
                self.source.write_text(value + "\n", encoding="utf-8")
                self.pin_synthetic_inputs()
                with self.assertRaises(dev_split.SplitError) as error:
                    self.select()
                self.assertNotIn("secret", str(error.exception))

    def test_non_utf8_source_fails(self):
        self.source.write_bytes(b"\xff")
        self.pin_synthetic_inputs()
        with self.assertRaisesRegex(dev_split.SplitError, "UTF-8"):
            self.select()

    def test_final_dataset_source_path_is_rejected_before_read(self):
        forbidden = self.root / "data/evaluation/tasks.jsonl"
        with patch.object(dev_split, "_read_bytes", side_effect=AssertionError("must not read")):
            with self.assertRaises(dev_split.SplitError):
                dev_split.select_development_split(forbidden, self.final, source_relative_path="data/evaluation/tasks.jsonl", provenance_manifest_path=self.provenance)
            with self.assertRaises(dev_split.SplitError):
                dev_split.select_development_split(forbidden, self.final, source_relative_path="data/grpo/validation.jsonl", provenance_manifest_path=self.provenance)

    def test_symlink_to_final_dataset_is_rejected_before_read(self):
        self.source.unlink()
        self.source.symlink_to(self.root / "data/evaluation/tasks.jsonl")
        with patch.object(dev_split, "_read_bytes", side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(dev_split.SplitError, "source path"):
                self.select()

    def test_changed_source_bytes_fail_provenance_check(self):
        raw = self.source.read_bytes()
        self.source.write_bytes(raw.replace(b'"task_id":0', b'"task_id":9', 1))
        with self.assertRaisesRegex(dev_split.SplitError, "Git blob SHA1"):
            self.select()
        self.source.write_bytes(raw + b"\n")
        with self.assertRaisesRegex(dev_split.SplitError, "byte count"):
            self.select()

    def test_changed_guard_fails_provenance_check(self):
        self.final.write_text(self.final.read_text().replace("10000", "30000"), encoding="utf-8")
        with self.assertRaisesRegex(dev_split.SplitError, "Git blob SHA1"):
            self.select()

    def test_missing_provenance_and_missing_source_are_actionable_errors(self):
        self.source.unlink()
        with self.assertRaisesRegex(dev_split.SplitError, "permitted development source unavailable"):
            self.select()
        self.provenance.unlink()
        with self.assertRaisesRegex(dev_split.SplitError, "provenance manifest unavailable"):
            self.select()

    def test_manifest_requires_unambiguous_pins_and_commit(self):
        original = json.loads(self.provenance.read_text())
        for mutated in ({**original, "source_commit": "main"}, {**original, "files": []}, {**original, "files": original["files"] * 2}):
            with self.subTest(mutated=mutated):
                self.provenance.write_text(json.dumps(mutated), encoding="utf-8")
                with self.assertRaises(dev_split.SplitError):
                    self.select()

    def test_write_id_only_artifacts_and_refuse_overwrite(self):
        manifest = self.select()
        tasks, metadata = dev_split.write_split(manifest, self.root / "runtime/dev20")
        self.assertEqual(json.loads(metadata.read_text()), manifest)
        self.assertEqual(hashlib.sha256(tasks.read_bytes()).hexdigest(), manifest["tasks_jsonl_sha256"])
        self.assertTrue(all(set(json.loads(line)) == {"task_id"} for line in tasks.read_text().splitlines()))
        with self.assertRaisesRegex(dev_split.SplitError, "refusing to overwrite"):
            dev_split.write_split(manifest, tasks.parent)

    def test_cli_requires_explicit_guard(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            dev_split.main(["--source", str(self.source), "--source-relative-path", "data/grpo/validation.jsonl"])
        self.assertEqual(error.exception.code, 2)

    def test_cli_offline_success_and_failure_no_output_artifacts(self):
        args = ["--source", str(self.source), "--source-relative-path", "data/grpo/validation.jsonl", "--final-id-manifest", str(self.final), "--provenance-manifest", str(self.provenance), "--seed", "77", "--output-dir", str(self.root / "result")]
        output = io.StringIO()
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), redirect_stdout(output):
            self.assertEqual(dev_split.main(args), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "prepared_not_evaluated")
        self.assertEqual(json.loads((self.root / "result/manifest.json").read_text())["selection"]["seed"], 77)
        self.source.unlink()
        args[-1] = str(self.root / "failed")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            dev_split.main(args)
        self.assertEqual(error.exception.code, 2)
        self.assertFalse((self.root / "failed").exists())


if __name__ == "__main__":
    unittest.main()
