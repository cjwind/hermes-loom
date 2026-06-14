"""Regression: Loom's memory serialization must round-trip through Hermes.

Hermes' ``memory`` tool refuses to write a memory file whose on-disk content
does not satisfy ``raw.strip() == "\\n§\\n".join(stripped_entries)`` — it treats
any mismatch as external drift, backs the file up to ``.bak.<ts>`` and aborts.

An earlier Loom serializer joined entries with ``"\\n\\n§\\n"`` (a blank line
before the ``§``). That single extra newline failed Hermes' equality check and
jammed Hermes out of USER.md entirely: every precipitation attempt was refused.
These tests pin the serializer (and the override write path that uses it) to the
exact runtime delimiter so the regression can never come back silently.
"""

from base import LoomTestCase

from hermes_loom import overrides
from hermes_loom.memory_parser import parse_entries, serialize_entries

# Hermes' canonical delimiter (tools/memory_tool.py: ENTRY_DELIMITER).
HERMES_DELIMITER = "\n§\n"


def hermes_detects_drift(raw: str) -> bool:
    """Replica of Hermes' round-trip drift signal (memory_tool._detect_external_drift).

    Returns True when Hermes would refuse to write this file.
    """
    if not raw.strip():
        return False
    parsed = [e.strip() for e in raw.split(HERMES_DELIMITER) if e.strip()]
    roundtrip = HERMES_DELIMITER.join(parsed)
    return raw.strip() != roundtrip


class TestSerializerRoundTrips(LoomTestCase):
    def test_serializer_uses_canonical_delimiter(self):
        out = serialize_entries(["a", "b", "c"])
        # Exactly Hermes' delimiter between entries — no blank-line variants.
        self.assertEqual(out, "a\n§\nb\n§\nc\n")
        self.assertNotIn("\n\n§", out)
        self.assertNotIn("§\n\n", out)

    def test_serializer_output_passes_hermes_drift_check(self):
        out = serialize_entries(["User likes tea.", "User uses NixOS.", "第三條中文條目。"])
        self.assertFalse(
            hermes_detects_drift(out),
            "Loom-serialized memory must round-trip through Hermes, or Hermes "
            "will refuse every future write to the file.",
        )

    def test_old_blank_line_format_would_have_been_rejected(self):
        # Guards the regression itself: the previous format DID trip the check.
        bad = "a\n\n§\nb\n\n§\nc\n"
        self.assertTrue(hermes_detects_drift(bad))

    def test_empty_entries_serialize_to_empty(self):
        self.assertEqual(serialize_entries([]), "")


class TestOverrideWriteRoundTrips(LoomTestCase):
    def test_edited_user_md_passes_hermes_drift_check(self):
        # Seed a file in Hermes' own canonical format, then tune it via Loom.
        self.write_memory("user", "User likes tea.\n§\nUser uses NixOS.")
        led = self.ledger()
        path = self.hermes_home / "memories" / "USER.md"
        key = parse_entries(path.read_text())[0]["key"]

        overrides.edit_memory_entry(led, "user", key, "User loves green tea.")

        raw = path.read_text(encoding="utf-8")
        self.assertFalse(
            hermes_detects_drift(raw),
            "After a Loom override, USER.md must still round-trip through Hermes.",
        )
