from pathlib import Path

from pmaa.skills.registry import LocalSkillRegistry


def test_local_skill_registry_loads_skill_markdown(tmp_path):
    skill_dir = tmp_path / "skills" / "research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: search_research
description: 用于搜索资料并生成研究报告
triggers:
  - 研究
  - 查询资料
enabled: true
---

# 使用规则

需要外部资料时使用。
""",
        encoding="utf-8",
    )

    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    skills = registry.list_skills()

    assert len(skills) == 1
    assert skills[0].skill_id == "search_research"
    assert skills[0].description == "用于搜索资料并生成研究报告"
    assert skills[0].triggers == ["研究", "查询资料"]
    assert skills[0].enabled is True
    assert "需要外部资料时使用" in skills[0].body


def test_disabled_skill_is_not_selected_or_formatted(tmp_path):
    skill_dir = tmp_path / "skills" / "writing"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: writing
description: 用于中文写作
triggers:
  - 写
enabled: true
---

# 输出要求

中文回答。
""",
        encoding="utf-8",
    )
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    disabled = registry.set_enabled("writing", False)

    assert disabled.enabled is False
    assert registry.match_skills("帮我写一段介绍") == []
    assert registry.format_catalog_for_prompt() == ""


def test_skill_registry_formats_enabled_skill_catalog_without_body_or_triggers(tmp_path):
    skill_dir = tmp_path / "skills" / "memory"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: memory_management
description: 用于写入和管理长期记忆
triggers:
  - 记住
  - 记忆
enabled: true
---

# 使用规则

用户要求保存稳定偏好时使用。
""",
        encoding="utf-8",
    )
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    prompt = registry.format_catalog_for_prompt()

    assert "<!-- Skill Catalog -->" in prompt
    assert "<name>memory_management</name>" in prompt
    assert "<tool_name>skill:memory_management</tool_name>" in prompt
    assert "<triggers>" not in prompt
    assert "<content>" not in prompt
    assert "用户要求保存稳定偏好时使用" not in prompt


def test_skill_registry_formats_selected_skill_detail_after_llm_choice(tmp_path):
    skill_dir = tmp_path / "skills" / "memory"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: memory_management
description: 用于写入和管理长期记忆
triggers:
  - 记住
enabled: true
---

# 使用规则

用户要求保存稳定偏好时使用。
""",
        encoding="utf-8",
    )
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    detail = registry.format_skill_detail_for_prompt("memory_management")

    assert "<!-- Selected Skill -->" in detail
    assert "<name>memory_management</name>" in detail
    assert "<content>" in detail
    assert "用户要求保存稳定偏好时使用" in detail
