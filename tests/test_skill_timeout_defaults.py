from pmaa.skills.registry import LocalSkillRegistry
from pmaa.skills.runtime import SkillRuntimeInstaller
from pmaa.skills.tool_binding import SkillToolBindingService


def test_skill_timeout_defaults_allow_slow_network_and_install_operations(tmp_path):
    registry = LocalSkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    binding_service = SkillToolBindingService()
    installer = SkillRuntimeInstaller()

    assert registry.import_skill_url.__kwdefaults__["timeout"] == 60
    assert registry.import_skill_source.__kwdefaults__["timeout"] == 60
    assert binding_service._timeout_seconds == 60
    assert installer._timeout_seconds == 600
