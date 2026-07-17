from pmaa.skills.registry import LocalSkillRegistry


def test_skill_registry_delete_removes_skill_directory_and_state(tmp_path):
    skill_dir = tmp_path / "skills" / "agent_browser"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: agent-browser
description: Browser automation CLI.
enabled: true
---

# agent-browser

Use browser automation.
""",
        encoding="utf-8",
    )
    (skill_dir / "_repo").mkdir()
    (skill_dir / "_repo" / "README.md").write_text("repo snapshot", encoding="utf-8")
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    registry.set_enabled("agent_browser", False)

    deleted = registry.delete("agent_browser")

    assert deleted.skill_id == "agent_browser"
    assert registry.get("agent_browser") is None
    assert not skill_dir.exists()
    assert "agent_browser" not in (tmp_path / "state.json").read_text(encoding="utf-8")


def test_skill_registry_delete_rejects_missing_skill(tmp_path):
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    try:
        registry.delete("missing")
    except ValueError as exc:
        assert "Skill does not exist" in str(exc)
    else:
        raise AssertionError("Expected delete to reject missing skill")
