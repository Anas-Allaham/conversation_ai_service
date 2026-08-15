from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from services.oral_assessment.models import CEFRLevel
from services.oral_assessment.storage import EncryptedLocalAudioStorage

from .helpers import PROJECT_ROOT


class EncryptedStorageTests(unittest.TestCase):
    def test_local_audio_is_encrypted_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = EncryptedLocalAudioStorage(Path(directory), Fernet.generate_key().decode())
            payload = b"raw-pcm-private-audio" * 100
            uri = storage.put("assessment-1", "response-1", payload, "audio/wav")
            stored_files = list(Path(directory).rglob("*.fernet"))
            self.assertEqual(1, len(stored_files))
            self.assertNotIn(payload, stored_files[0].read_bytes())
            self.assertEqual(payload, storage.get(uri))

    def test_retention_removes_only_expired_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = EncryptedLocalAudioStorage(Path(directory), Fernet.generate_key().decode())
            old_uri = storage.put("assessment-1", "old", b"old", "audio/wav")
            new_uri = storage.put("assessment-1", "new", b"new", "audio/wav")
            old_path = storage._path(old_uri)
            os.utime(old_path, (time.time() - 40 * 86400, time.time() - 40 * 86400))
            self.assertEqual(1, storage.delete_expired(30))
            self.assertEqual(b"new", storage.get(new_uri))


class GoldenCaseTests(unittest.TestCase):
    def test_all_target_levels_have_original_golden_fixture(self) -> None:
        directory = PROJECT_ROOT / "services" / "oral_assessment" / "golden_cases"
        cases = [json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*.json")]
        self.assertEqual({level.value for level in CEFRLevel}, {case["target_level"] for case in cases})
        for case in cases:
            self.assertIn("synthetic", case["note"].lower())
            self.assertFalse(case["expected"].get("grammar_penalty", False))


if __name__ == "__main__":
    unittest.main()
