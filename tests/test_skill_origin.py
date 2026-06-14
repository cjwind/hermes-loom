"""Unit tests for the central skill origin classifier + integration with
build_records (skill records tagged, summary counts, hidden-by-default rule)."""

from base import LoomTestCase
from hermes_loom import skill_origin, service


AGENT = "---\nname: a\ncreated_by: agent\nauthor: whoever\n---\nbody\n"
OFFICIAL = "---\nname: b\ndescription: off\nauthor: Hermes Agent + Teknium\n---\nbody\n"
OFFICIAL2 = "---\nname: b2\nauthor: Nous Research\n---\nbody\n"
PORTED = "---\nname: b3\nauthor: Cocoon AI (hello@x), ported by Hermes Agent\n---\nbody\n"
COMMUNITY = "---\nname: c\nauthor: 宝玉 (JimLiu)\n---\nbody\n"
NO_FM = "# just a heading\nno frontmatter here\n"
LIST_AUTHOR = "---\nname: d\nauthor: [kshitijk4poor, alt-glitch]\n---\nbody\n"


class TestClassifier(LoomTestCase):
    def c(self, fm):
        return skill_origin.classify_skill_origin(fm)

    def test_created_by_agent_wins(self):
        # created_by:agent beats any author value
        r = self.c({"created_by": "agent", "author": "Hermes Agent"})
        self.assertTrue(r["is_agent_created"])
        self.assertEqual(r["origin_type"], "agent_created")

    def test_official_author(self):
        for a in ("Hermes Agent", "Hermes Agent + Teknium", "Nous Research",
                  "Cocoon AI (hello@x), ported by Hermes Agent", "0xbyt4, Hermes Agent"):
            r = self.c({"author": a})
            self.assertEqual(r["origin_type"], "hermes_official", a)
            self.assertFalse(r["is_agent_created"])

    def test_community_author(self):
        for a in ("宝玉 (JimLiu)", "community", "Mibayy", "SHL0MS", "Hugging Face"):
            self.assertEqual(self.c({"author": a})["origin_type"], "community", a)

    def test_missing_frontmatter_is_community(self):
        for fm in (None, {}, {"name": "x"}):
            r = self.c(fm)
            self.assertEqual(r["origin_type"], "community")
            self.assertFalse(r["is_agent_created"])

    def test_author_as_list_is_community(self):
        r = self.c({"author": ["a", "b"]})
        self.assertEqual(r["origin_type"], "community")

    def test_created_by_not_agent_falls_through(self):
        # created_by present but not "agent" → fall through to author rules
        self.assertEqual(self.c({"created_by": "human", "author": "Hermes Agent"})["origin_type"], "hermes_official")
        self.assertEqual(self.c({"created_by": "import"})["origin_type"], "community")

    def test_is_hermes_official_author_helper(self):
        self.assertTrue(skill_origin.is_hermes_official_author("Hermes Agent"))
        self.assertTrue(skill_origin.is_hermes_official_author("NOUS RESEARCH"))
        self.assertFalse(skill_origin.is_hermes_official_author("community"))
        self.assertFalse(skill_origin.is_hermes_official_author(None))
        self.assertFalse(skill_origin.is_hermes_official_author(["x"]))


class TestBuildRecordsOrigin(LoomTestCase):
    def _seed_skills(self):
        self.write_memory("user", "User likes tea.")
        self.write_skill("productivity", "agentskill", AGENT)
        self.write_skill("productivity", "offskill", OFFICIAL)
        self.write_skill("productivity", "commskill", COMMUNITY)
        self.write_skill("productivity", "nofmskill", NO_FM)

    def test_skill_records_tagged(self):
        # skill name = frontmatter `name` (a/b/c), or dir name when no frontmatter
        self._seed_skills()
        led = self.ledger()
        out = service.build_records(led)
        skills = {r["target_key"]: r for r in out["records"] if r["target_type"] == "skill"}
        self.assertTrue(skills["a"]["is_agent_created"])
        self.assertEqual(skills["a"]["origin_type"], "agent_created")
        self.assertEqual(skills["b"]["origin_type"], "hermes_official")
        self.assertEqual(skills["c"]["origin_type"], "community")
        self.assertEqual(skills["nofmskill"]["origin_type"], "community")

    def test_skill_summary_counts(self):
        self._seed_skills()
        out = service.build_records(self.ledger())
        ss = out["skill_summary"]
        self.assertEqual(ss["total"], 4)
        self.assertEqual(ss["agent_created"], 1)
        self.assertEqual(ss["hermes_official"], 1)
        self.assertEqual(ss["community"], 2)

    def test_ui_filter_rule_hides_non_agent_skills(self):
        """Data-level mirror of the UI filter: only agent-created skills show,
        memory/user entries always show, nothing is deleted."""
        self._seed_skills()
        out = service.build_records(self.ledger())
        visible = [r for r in out["records"]
                   if r["target_type"] != "skill" or r.get("is_agent_created")]
        vis_skills = [r["target_key"] for r in visible if r["target_type"] == "skill"]
        self.assertEqual(vis_skills, ["a"])
        # non-agent skills still exist in the full payload (not deleted)
        all_skills = [r["target_key"] for r in out["records"] if r["target_type"] == "skill"]
        self.assertEqual(len(all_skills), 4)
