import json
import shlex
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx

from pmaa.schemas.skill import SkillRecord


@dataclass(frozen=True)
class SkillImportItem:
    skill_id: str
    name: str
    status: str
    message: str = ""


@dataclass(frozen=True)
class SkillImportResult:
    imported: list[SkillImportItem] = field(default_factory=list)
    skipped: list[SkillImportItem] = field(default_factory=list)
    failed: list[SkillImportItem] = field(default_factory=list)

    @property
    def imported_count(self) -> int:
        return len(self.imported)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def failed_count(self) -> int:
        return len(self.failed)


class LocalSkillRegistry:
    def __init__(
        self,
        skills_root: str | Path = "skills",
        state_path: str | Path = "data/pmaa_skill_state.json",
    ) -> None:
        self._skills_root = Path(skills_root)
        self._state_path = Path(state_path)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

    def list_skills(self) -> list[SkillRecord]:
        state = self._load_state()
        skills = [
            self._load_skill(path, state)
            for path in sorted(self._skills_root.glob("*/SKILL.md"))
        ]
        return sorted(skills, key=lambda skill: skill.name.lower())

    def get(self, skill_id: str) -> SkillRecord | None:
        for skill in self.list_skills():
            if skill.skill_id == skill_id:
                return skill
        return None

    def set_enabled(self, skill_id: str, enabled: bool) -> SkillRecord:
        current = self.get(skill_id)
        if current is None:
            raise ValueError(f"Skill does not exist: {skill_id}")
        state = self._load_state()
        state.setdefault(skill_id, {})["enabled"] = enabled
        self._save_state(state)
        updated = self.get(skill_id)
        if updated is None:
            raise ValueError(f"Skill does not exist after update: {skill_id}")
        return updated

    def match_skills(self, query: str, limit: int = 5) -> list[SkillRecord]:
        normalized_query = query.lower()
        scored: list[tuple[int, SkillRecord]] = []
        for skill in self.list_skills():
            if not skill.enabled:
                continue
            score = self._score_skill(skill, normalized_query)
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
        return [skill for _, skill in scored[:limit]]

    def list_enabled_skills(self) -> list[SkillRecord]:
        return [skill for skill in self.list_skills() if skill.enabled]

    def format_catalog_for_prompt(self, limit: int = 50) -> str:
        skills = self.list_enabled_skills()[:limit]
        if not skills:
            return ""
        blocks = [
            "<!-- Skill Catalog -->",
            "<available_skills>",
        ]
        for skill in skills:
            blocks.extend(
                [
                    "  <skill>",
                    f"    <id>{skill.skill_id}</id>",
                    f"    <tool_name>skill:{skill.skill_id}</tool_name>",
                    f"    <name>{skill.name}</name>",
                    f"    <description>{skill.description}</description>",
                    "  </skill>",
                ]
            )
        blocks.append("</available_skills>")
        return "\n".join(blocks)

    def format_skill_detail_for_prompt(self, skill_id: str) -> str:
        skill = self.get(skill_id)
        if skill is None or not skill.enabled:
            return ""
        return "\n".join(
            [
                "<!-- Selected Skill -->",
                "<selected_skill>",
                f"  <id>{skill.skill_id}</id>",
                f"  <tool_name>skill:{skill.skill_id}</tool_name>",
                f"  <name>{skill.name}</name>",
                f"  <description>{skill.description}</description>",
                "  <content>",
                self._indent(skill.body.strip(), "    "),
                "  </content>",
                "</selected_skill>",
            ]
        )

    def format_for_prompt(self, query: str, limit: int = 5) -> str:
        return self.format_catalog_for_prompt(limit=limit)

    def import_skill_markdown(
        self,
        content: str,
        *,
        overwrite: bool = False,
    ) -> SkillImportResult:
        item, validated_content = self._validate_import_content(content)
        if item.status == "failed":
            return SkillImportResult(failed=[item])

        skill_dir = self._skills_root / item.skill_id
        skill_path = skill_dir / "SKILL.md"
        if skill_path.exists() and not overwrite:
            return SkillImportResult(
                skipped=[
                    SkillImportItem(
                        skill_id=item.skill_id,
                        name=item.name,
                        status="skipped",
                        message="Skill already exists.",
                    )
                ]
            )

        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(validated_content, encoding="utf-8")
        state = self._load_state()
        state.setdefault(item.skill_id, {})["enabled"] = True
        self._save_state(state)
        return SkillImportResult(
            imported=[
                SkillImportItem(
                    skill_id=item.skill_id,
                    name=item.name,
                    status="imported",
                    message="Imported and enabled.",
                )
            ]
        )

    def import_skill_zip(
        self,
        archive_bytes: bytes,
        *,
        skill_name: str = "",
        overwrite: bool = False,
        preserve_repo_snapshot: bool = False,
    ) -> SkillImportResult:
        imported: list[SkillImportItem] = []
        skipped: list[SkillImportItem] = []
        failed: list[SkillImportItem] = []
        try:
            archive = ZipFile(BytesIO(archive_bytes))
        except BadZipFile:
            return SkillImportResult(
                failed=[
                    SkillImportItem(
                        skill_id="",
                        name="zip",
                        status="failed",
                        message="Invalid zip archive.",
                    )
                ]
            )

        with archive:
            skill_paths = _select_skill_paths(archive.namelist(), skill_name)
            for skill_path in skill_paths:
                result = self._import_skill_package_from_zip(
                    archive,
                    skill_path,
                    overwrite=overwrite,
                    preserve_repo_snapshot=preserve_repo_snapshot,
                )
                imported.extend(result.imported)
                skipped.extend(result.skipped)
                failed.extend(result.failed)
        return SkillImportResult(imported=imported, skipped=skipped, failed=failed)

    def import_skill_url(
        self,
        url: str,
        *,
        overwrite: bool = False,
        timeout: float = 20,
    ) -> SkillImportResult:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        if _looks_like_zip_response(url, response):
            return self.import_skill_zip(response.content, overwrite=overwrite)
        return self.import_skill_markdown(response.text, overwrite=overwrite)

    def import_skill_source(
        self,
        source: str,
        *,
        skill_name: str = "",
        overwrite: bool = False,
        timeout: float = 20,
    ) -> SkillImportResult:
        parsed_source, parsed_skill_name = _parse_skill_source(source)
        active_skill_name = skill_name.strip() or parsed_skill_name
        if _is_github_repo_url(parsed_source):
            return self._import_github_skill(
                parsed_source,
                active_skill_name,
                overwrite=overwrite,
                timeout=timeout,
            )
        return self.import_skill_url(parsed_source, overwrite=overwrite, timeout=timeout)

    def _import_github_skill(
        self,
        repo_url: str,
        skill_name: str,
        *,
        overwrite: bool,
        timeout: float,
    ) -> SkillImportResult:
        if not skill_name:
            return SkillImportResult(
                failed=[
                    SkillImportItem(
                        skill_id="",
                        name="github",
                        status="failed",
                        message="GitHub repo import requires --skill or skill name.",
                    )
                ]
            )
        errors: list[str] = []
        for archive_url in _github_repo_zip_candidates(repo_url):
            try:
                response = httpx.get(archive_url, timeout=timeout)
                response.raise_for_status()
            except Exception as exc:
                errors.append(f"{archive_url}: {exc}")
                continue
            result = self.import_skill_zip(
                response.content,
                skill_name=skill_name,
                overwrite=overwrite,
                preserve_repo_snapshot=True,
            )
            if result.imported or result.skipped:
                return result
            errors.extend(item.message for item in result.failed)

        for raw_url in _github_skill_raw_candidates(repo_url, skill_name):
            try:
                response = httpx.get(raw_url, timeout=timeout)
                response.raise_for_status()
            except Exception as exc:
                errors.append(f"{raw_url}: {exc}")
                continue
            result = self.import_skill_markdown(response.text, overwrite=overwrite)
            if result.imported or result.skipped:
                return result
            errors.extend(item.message for item in result.failed)
        return SkillImportResult(
            failed=[
                SkillImportItem(
                    skill_id=_normalize_skill_id(skill_name),
                    name=skill_name,
                    status="failed",
                    message="Could not import GitHub skill. Tried raw SKILL.md candidates.",
                )
            ]
        )

    def _import_skill_package_from_zip(
        self,
        archive: ZipFile,
        skill_path: str,
        *,
        overwrite: bool,
        preserve_repo_snapshot: bool,
    ) -> SkillImportResult:
        content = archive.read(skill_path).decode("utf-8")
        item, validated_content = self._validate_import_content(content)
        if item.status == "failed":
            return SkillImportResult(failed=[item])

        skill_dir = self._skills_root / item.skill_id
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists() and not overwrite:
            return SkillImportResult(
                skipped=[
                    SkillImportItem(
                        skill_id=item.skill_id,
                        name=item.name,
                        status="skipped",
                        message="Skill already exists.",
                    )
                ]
            )

        package_prefix = str(Path(skill_path).parent).replace("\\", "/").rstrip("/")
        skill_dir.mkdir(parents=True, exist_ok=True)
        for member in archive.namelist():
            normalized_member = member.replace("\\", "/")
            if normalized_member.endswith("/"):
                continue
            if not normalized_member.startswith(f"{package_prefix}/"):
                continue
            relative = normalized_member[len(package_prefix) + 1 :]
            if not relative or _is_unsafe_relative_path(relative):
                continue
            target = skill_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative == "SKILL.md":
                target.write_text(validated_content, encoding="utf-8")
            else:
                target.write_bytes(archive.read(member))
        if preserve_repo_snapshot:
            self._write_repo_snapshot_from_zip(archive, skill_dir)

        state = self._load_state()
        state.setdefault(item.skill_id, {})["enabled"] = True
        self._save_state(state)
        return SkillImportResult(
            imported=[
                SkillImportItem(
                    skill_id=item.skill_id,
                    name=item.name,
                    status="imported",
                    message="Imported package and enabled.",
                )
            ]
        )

    def _write_repo_snapshot_from_zip(self, archive: ZipFile, skill_dir: Path) -> None:
        root_prefix = _archive_common_root(archive.namelist())
        repo_dir = skill_dir / "_repo"
        for member in archive.namelist():
            normalized_member = member.replace("\\", "/")
            if normalized_member.endswith("/"):
                continue
            relative = (
                normalized_member[len(root_prefix) :]
                if root_prefix and normalized_member.startswith(root_prefix)
                else normalized_member
            )
            if not relative or _is_unsafe_relative_path(relative):
                continue
            target = repo_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))

    def _load_skill(
        self,
        path: Path,
        state: dict[str, dict[str, Any]],
    ) -> SkillRecord:
        text = path.read_text(encoding="utf-8")
        metadata, body = _parse_skill_markdown(text)
        name = str(metadata.get("name") or path.parent.name).strip()
        skill_id = _normalize_skill_id(name)
        enabled = bool(metadata.get("enabled", True))
        if skill_id in state and "enabled" in state[skill_id]:
            enabled = bool(state[skill_id]["enabled"])
        return SkillRecord(
            skill_id=skill_id,
            name=name,
            description=str(metadata.get("description", "")).strip(),
            triggers=[str(item).strip() for item in metadata.get("triggers", []) if str(item).strip()],
            enabled=enabled,
            source_path=path,
            body=body.strip(),
        )

    @staticmethod
    def _score_skill(skill: SkillRecord, normalized_query: str) -> int:
        score = 0
        searchable = f"{skill.name} {skill.description}".lower()
        for token in normalized_query.split():
            if token and token in searchable:
                score += 1
        return score

    @staticmethod
    def _validate_import_content(content: str) -> tuple[SkillImportItem, str]:
        metadata, body = _parse_skill_markdown(content)
        name = str(metadata.get("name", "")).strip()
        description = str(metadata.get("description", "")).strip()
        triggers = metadata.get("triggers", [])
        if not name:
            return (
                SkillImportItem("", "", "failed", "Missing required field: name."),
                content,
            )
        skill_id = _normalize_skill_id(name)
        if not description:
            return (
                SkillImportItem(
                    skill_id,
                    name,
                    "failed",
                    "Missing required field: description.",
                ),
                content,
            )
        if not body.strip():
            return (
                SkillImportItem(skill_id, name, "failed", "Skill body is empty."),
                content,
            )
        derived_triggers = (
            [str(item).strip() for item in triggers if str(item).strip()]
            if isinstance(triggers, list)
            else []
        )
        normalized_content = _normalize_skill_frontmatter_for_import(
            content,
            triggers=derived_triggers,
        )
        return (
            SkillImportItem(skill_id, name, "validated"),
            normalized_content,
        )

    def _load_state(self) -> dict[str, dict[str, Any]]:
        if not self._state_path.exists():
            return {}
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _save_state(self, state: dict[str, dict[str, Any]]) -> None:
        self._state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _indent(text: str, prefix: str) -> str:
        return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def _parse_skill_markdown(text: str) -> tuple[dict[str, Any], str]:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    lines = stripped.splitlines()
    metadata_lines: list[str] = []
    end_index = -1
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
        metadata_lines.append(line)
    if end_index == -1:
        return {}, text
    body = "\n".join(lines[end_index + 1 :])
    return _parse_frontmatter(metadata_lines), body


def _parse_frontmatter(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_list_key = ""
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list_key:
            metadata.setdefault(current_list_key, []).append(stripped[2:].strip())
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_list_key = ""
        if value == "":
            metadata[key] = []
            current_list_key = key
        elif value.lower() in {"true", "false"}:
            metadata[key] = value.lower() == "true"
        elif value.startswith("[") and value.endswith("]"):
            metadata[key] = [
                item.strip().strip("'\"")
                for item in value[1:-1].split(",")
                if item.strip()
            ]
        else:
            metadata[key] = value.strip("'\"")
    return metadata


def _normalize_skill_id(name: str) -> str:
    return "_".join(name.lower().strip().replace("-", "_").split())


def _parse_skill_source(source: str) -> tuple[str, str]:
    stripped = source.strip()
    if stripped.startswith("npx ") or stripped.startswith("pnpm ") or stripped.startswith("bunx "):
        parts = shlex.split(stripped)
        repo_url = ""
        skill_name = ""
        for index, part in enumerate(parts):
            if part.startswith("http://") or part.startswith("https://"):
                repo_url = part
            if part == "--skill" and index + 1 < len(parts):
                skill_name = parts[index + 1]
        return repo_url or stripped, skill_name
    return stripped, ""


def _is_github_repo_url(url: str) -> bool:
    parts = _github_owner_repo(url)
    return parts is not None and "/blob/" not in url and "/raw/" not in url


def _github_owner_repo(url: str) -> tuple[str, str] | None:
    normalized = url.strip().removesuffix("/")
    prefix = "https://github.com/"
    if not normalized.startswith(prefix):
        return None
    path = normalized[len(prefix) :]
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return None
    return segments[0], segments[1].removesuffix(".git")


def _github_skill_raw_candidates(repo_url: str, skill_name: str) -> list[str]:
    owner_repo = _github_owner_repo(repo_url)
    if owner_repo is None:
        return []
    owner, repo = owner_repo
    encoded_skill = skill_name.strip().strip("/")
    paths = [
        f"{encoded_skill}/SKILL.md",
        f"skills/{encoded_skill}/SKILL.md",
        "SKILL.md",
    ]
    branches = ["main", "master"]
    return [
        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        for branch in branches
        for path in paths
    ]


def _github_repo_zip_candidates(repo_url: str) -> list[str]:
    owner_repo = _github_owner_repo(repo_url)
    if owner_repo is None:
        return []
    owner, repo = owner_repo
    return [
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main",
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master",
    ]


def _select_skill_paths(names: list[str], skill_name: str = "") -> list[str]:
    skill_paths = [
        name.replace("\\", "/")
        for name in names
        if Path(name).name == "SKILL.md"
    ]
    if not skill_name:
        return skill_paths

    normalized_skill = skill_name.strip().strip("/").lower()
    preferred: list[str] = []
    fallback: list[str] = []
    for path in skill_paths:
        parent_parts = [part.lower() for part in Path(path).parent.parts]
        if parent_parts and parent_parts[-1] == normalized_skill:
            preferred.append(path)
        elif normalized_skill in parent_parts:
            fallback.append(path)
    return preferred or fallback


def _is_unsafe_relative_path(path: str) -> bool:
    parts = Path(path).parts
    return any(part in {"", ".", ".."} for part in parts)


def _archive_common_root(names: list[str]) -> str:
    roots = {
        name.replace("\\", "/").split("/", 1)[0]
        for name in names
        if "/" in name.replace("\\", "/")
    }
    if len(roots) != 1:
        return ""
    return f"{next(iter(roots))}/"


def _looks_like_zip_response(url: str, response: httpx.Response) -> bool:
    headers = getattr(response, "headers", {})
    content_type = headers.get("content-type", "").lower()
    content = getattr(response, "content", b"")
    return (
        url.lower().endswith(".zip")
        or "application/zip" in content_type
        or content[:4] == b"PK\x03\x04"
    )


def _derive_triggers(name: str, description: str) -> list[str]:
    stopwords = {"for", "and", "the", "with", "when", "use", "uses"}
    raw_terms: list[str] = []
    for chunk in [name, *description.replace(".", " ").replace(",", " ").split()]:
        cleaned = chunk.strip().strip("()[]{}:;,.").lower()
        if len(cleaned) >= 3 and cleaned not in stopwords and cleaned not in raw_terms:
            raw_terms.append(cleaned)
    return raw_terms[:6] or [_normalize_skill_id(name)]


def _normalize_skill_frontmatter_for_import(content: str, triggers: list[str]) -> str:
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return content
    lines = stripped.splitlines()
    end_index = -1
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index == -1:
        return content

    frontmatter = lines[: end_index + 1]
    body = lines[end_index + 1 :]
    replaced = False
    for index, line in enumerate(frontmatter):
        if line.strip().startswith("enabled:"):
            frontmatter[index] = "enabled: true"
            replaced = True
            break
    if not replaced:
        frontmatter.insert(end_index, "enabled: true")
        end_index += 1

    has_triggers = any(line.strip().startswith("triggers:") for line in frontmatter)
    if not has_triggers and triggers:
        trigger_lines = ["triggers:", *[f"  - {trigger}" for trigger in triggers]]
        insert_index = max(1, len(frontmatter) - 1)
        frontmatter[insert_index:insert_index] = trigger_lines
    return "\n".join([*frontmatter, *body]).strip() + "\n"
