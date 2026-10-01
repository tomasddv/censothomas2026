"""Regression tests for manual review persistence (no Streamlit or network)."""

import copy
import unittest

from review_state import merge_review_records, restore_manual


AUTO = {"ok": True, "src": "auto", "corr": None}
PENDING = {"ok": False, "src": None, "corr": None}
MANUAL_OK = {"ok": True, "src": "manual", "corr": None}


class ReviewStateTests(unittest.TestCase):
    def test_saved_correction_overrides_new_automatic_ok(self):
        base = {"a": copy.deepcopy(AUTO), "b": copy.deepcopy(PENDING)}
        saved = {"a": {"ok": False, "src": "manual", "corr": 0},
                 "b": copy.deepcopy(MANUAL_OK), "historical": MANUAL_OK}
        restored = restore_manual(base, saved)
        self.assertEqual(restored["a"], {"ok": False, "src": "manual", "corr": 0.0})
        self.assertEqual(restored["b"], MANUAL_OK)
        self.assertNotIn("historical", restored)
        self.assertEqual(base["a"], AUTO)

    def test_invalid_and_automatic_saved_values_do_not_restore(self):
        for correction in [float("nan"), float("inf"), -1, True, "bad"]:
            with self.subTest(correction=correction):
                saved = {"a": {"ok": True, "src": "manual", "corr": correction}}
                self.assertEqual(restore_manual({"a": PENDING}, saved), {"a": PENDING})
        self.assertEqual(restore_manual({"a": PENDING}, {"a": AUTO}), {"a": PENDING})
        self.assertEqual(restore_manual({"a": PENDING}, {"a": {"ok": "false"}}), {"a": PENDING})

    def test_merge_preserves_unrelated_and_other_session_work(self):
        existing = {"a": MANUAL_OK, "other-session": {"ok": False, "src": "manual", "corr": 8},
                    "historical": MANUAL_OK}
        local = {"a": {"ok": False, "src": "manual", "corr": 2},
                 "other-session": PENDING}
        before = copy.deepcopy(existing)
        merged = merge_review_records(existing, local, {"a"})
        self.assertEqual(merged["a"]["corr"], 2)
        self.assertEqual(merged["other-session"]["corr"], 8)
        self.assertEqual(merged["historical"], MANUAL_OK)
        self.assertEqual(existing, before)

    def test_only_explicit_pending_change_deletes(self):
        existing = {"a": MANUAL_OK, "b": MANUAL_OK}
        self.assertEqual(merge_review_records(existing, {"a": PENDING}), existing)
        self.assertEqual(merge_review_records(existing, {"a": PENDING}, {"a"}), {"b": MANUAL_OK})
        self.assertEqual(merge_review_records(existing, {}, {"a"}), existing)

    def test_auto_and_invalid_changes_never_overwrite(self):
        existing = {"a": MANUAL_OK}
        for value in [AUTO, {"ok": False, "src": "manual", "corr": float("nan")}, None]:
            self.assertEqual(merge_review_records(existing, {"a": value}, {"a"}), existing)
        self.assertEqual(merge_review_records({}, {"a": AUTO}, {"a"}), {})

    def test_correction_takes_precedence_over_inconsistent_ok(self):
        result = merge_review_records({}, {"a": {"ok": True, "src": "manual", "corr": 1}}, {"a"})
        self.assertEqual(result["a"], {"ok": False, "src": "manual", "corr": 1.0})


if __name__ == "__main__":
    unittest.main()
