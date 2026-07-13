import json
import os
import tempfile
import unittest

from archive_provenance import (
    _canonical_json_hash,
    _current_git_commit,
    _patch_content_hash,
    build_archive_metadata,
)


class ArchiveProvenanceTests(unittest.TestCase):
    def test_canonical_hash_is_order_independent_and_characterized(self):
        self.assertEqual(_canonical_json_hash({"b": 2, "a": 1}), "43258cff783fe703")
        self.assertEqual(_canonical_json_hash({"a": 1, "b": 2}), "43258cff783fe703")

    def test_patch_hash_tracks_existing_contents_and_ignores_missing_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            patch_path = os.path.join(temp_dir, "patch.json")
            with open(patch_path, "w", encoding="utf-8") as handle:
                json.dump({"value": 1}, handle)
            first = _patch_content_hash([patch_path, os.path.join(temp_dir, "missing.json")])
            duplicate = _patch_content_hash([patch_path, patch_path])
            self.assertEqual(first, duplicate)
            self.assertNotEqual(first, "none")
            with open(patch_path, "w", encoding="utf-8") as handle:
                json.dump({"value": 2}, handle)
            self.assertNotEqual(first, _patch_content_hash([patch_path]))
        self.assertEqual(_patch_content_hash([]), "none")

    def test_metadata_schema_is_stable(self):
        metadata = build_archive_metadata(
            {"fusion_params": {"x": 1}},
            prediction_seed=42,
            patch_paths=(),
            git_commit="abc123",
        )
        self.assertEqual(metadata, {
            "archive_schema_version": "2",
            "runtime_config_hash": _canonical_json_hash({"fusion_params": {"x": 1}}),
            "patch_config_hash": "none",
            "prediction_seed": "42",
            "git_commit": "abc123",
        })

    def test_git_commit_returns_a_nonempty_string(self):
        self.assertTrue(_current_git_commit(os.getcwd()))


if __name__ == "__main__":
    unittest.main()
