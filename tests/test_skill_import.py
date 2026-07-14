from zipfile import ZipFile

from pmaa.skills.registry import LocalSkillRegistry


VALID_SKILL = """---
name: imported_skill
description: Imported skill for testing.
triggers:
  - import
enabled: true
---

# Rules

Use this imported skill.
"""

SKILL_WITHOUT_TRIGGERS = """---
name: agent-browser
description: Browser automation CLI for AI agents.
---

# agent-browser

Use when browser automation is required.
"""


def test_import_skill_markdown_saves_enabled_by_default(tmp_path):
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    result = registry.import_skill_markdown(VALID_SKILL)
    imported = registry.get("imported_skill")

    assert result.imported_count == 1
    assert result.skipped_count == 0
    assert imported is not None
    assert imported.enabled is True
    assert imported.source_path == tmp_path / "skills" / "imported_skill" / "SKILL.md"
    assert registry.match_skills("imported testing")[0].skill_id == "imported_skill"


def test_import_skill_markdown_accepts_real_world_skill_without_triggers(tmp_path):
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    result = registry.import_skill_markdown(SKILL_WITHOUT_TRIGGERS)
    imported = registry.get("agent_browser")

    assert result.imported_count == 1
    assert imported is not None
    assert imported.enabled is True
    assert imported.triggers == []


def test_import_skill_markdown_skips_existing_by_default(tmp_path):
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    first = registry.import_skill_markdown(VALID_SKILL)
    second = registry.import_skill_markdown(
        VALID_SKILL.replace("Use this imported skill.", "Changed body.")
    )

    assert first.imported_count == 1
    assert second.imported_count == 0
    assert second.skipped_count == 1
    assert "Use this imported skill." in registry.get("imported_skill").body


def test_import_skill_zip_imports_multiple_skill_files(tmp_path):
    zip_path = tmp_path / "skills.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("one/SKILL.md", VALID_SKILL)
        archive.writestr(
            "nested/two/SKILL.md",
            VALID_SKILL.replace("imported_skill", "second_skill").replace(
                "- import",
                "- second",
            ),
        )
        archive.writestr("README.md", "ignored")

    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    result = registry.import_skill_zip(zip_path.read_bytes())

    assert result.imported_count == 2
    assert registry.get("imported_skill") is not None
    assert registry.get("second_skill") is not None
    assert registry.get("imported_skill").enabled is True
    assert registry.get("second_skill").enabled is True


def test_import_skill_zip_preserves_package_files(tmp_path):
    zip_path = tmp_path / "repo.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("repo-main/skills/agent-browser/SKILL.md", VALID_SKILL)
        archive.writestr("repo-main/skills/agent-browser/scripts/install.py", "print('install')")
        archive.writestr("repo-main/skills/agent-browser/examples/demo.txt", "demo")

    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    result = registry.import_skill_zip(zip_path.read_bytes(), skill_name="agent-browser")

    assert result.imported_count == 1
    assert (tmp_path / "skills" / "imported_skill" / "scripts" / "install.py").exists()
    assert (tmp_path / "skills" / "imported_skill" / "examples" / "demo.txt").exists()


def test_import_skill_url_downloads_and_imports(monkeypatch, tmp_path):
    class FakeResponse:
        text = VALID_SKILL

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: float):
        assert url == "https://example.com/SKILL.md"
        assert timeout == 20
        return FakeResponse()

    monkeypatch.setattr("pmaa.skills.registry.httpx.get", fake_get)
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    result = registry.import_skill_url("https://example.com/SKILL.md")

    assert result.imported_count == 1
    assert registry.get("imported_skill") is not None


def test_import_skill_source_supports_npx_skills_add_command(monkeypatch, tmp_path):
    requested_urls: list[str] = []
    zip_path = tmp_path / "repo.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("repo-main/skills/agent-browser/SKILL.md", VALID_SKILL)
        archive.writestr("repo-main/skills/agent-browser/scripts/install.py", "print('install')")
        archive.writestr("repo-main/skill-data/core/SKILL.md", SKILL_WITHOUT_TRIGGERS)

    class NotFoundResponse:
        text = "not found"

        def raise_for_status(self) -> None:
            raise RuntimeError("404")

    class SkillResponse:
        content = zip_path.read_bytes()
        text = ""
        headers = {"content-type": "application/zip"}

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: float):
        requested_urls.append(url)
        if url == (
            "https://codeload.github.com/vercel-labs/agent-browser/zip/refs/heads/main"
        ):
            return SkillResponse()
        return NotFoundResponse()

    monkeypatch.setattr("pmaa.skills.registry.httpx.get", fake_get)
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    result = registry.import_skill_source(
        "npx skills add https://github.com/vercel-labs/agent-browser --skill agent-browser"
    )

    assert result.imported_count == 1
    assert registry.get("imported_skill") is not None
    assert requested_urls[0].endswith("/zip/refs/heads/main")
    assert (tmp_path / "skills" / "imported_skill" / "scripts" / "install.py").exists()
    assert (tmp_path / "skills" / "imported_skill" / "_repo" / "skill-data" / "core" / "SKILL.md").exists()


def test_import_skill_source_supports_github_repo_and_skill_name(monkeypatch, tmp_path):
    class SkillResponse:
        content = VALID_SKILL.encode("utf-8")
        text = VALID_SKILL
        headers = {"content-type": "text/plain"}

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: float):
        assert url == (
            "https://raw.githubusercontent.com/vercel-labs/"
            "agent-browser/main/agent-browser/SKILL.md"
        )
        return SkillResponse()

    monkeypatch.setattr("pmaa.skills.registry.httpx.get", fake_get)
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    result = registry.import_skill_source(
        "https://github.com/vercel-labs/agent-browser",
        skill_name="agent-browser",
    )

    assert result.imported_count == 1
    assert registry.get("imported_skill") is not None


def test_import_skill_url_detects_zip_content(monkeypatch, tmp_path):
    zip_path = tmp_path / "skills.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("one/SKILL.md", VALID_SKILL)

    class ZipResponse:
        content = zip_path.read_bytes()
        text = ""
        headers = {"content-type": "application/zip"}

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: float):
        assert url == "https://example.com/skills.zip"
        return ZipResponse()

    monkeypatch.setattr("pmaa.skills.registry.httpx.get", fake_get)
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")

    result = registry.import_skill_url("https://example.com/skills.zip")

    assert result.imported_count == 1
    assert registry.get("imported_skill") is not None
