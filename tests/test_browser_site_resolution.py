from pmaa.workflow.graph import _extract_url_to_open
from pmaa.workflow.graph import _tool_input_for_direct_call


def test_extracts_plain_english_brand_homepage_before_search():
    assert _extract_url_to_open("open vercel website") == "https://vercel.com"


def test_extracts_plain_english_brand_from_chinese_open_request():
    assert _extract_url_to_open("打开vercel网站") == "https://vercel.com"


def test_simple_open_uses_default_browser_open_url_action():
    request = _tool_input_for_direct_call("skill:agent_browser", "打开vercel网站")

    assert request == {
        "action": "browser.open_url",
        "args": {"url": "https://vercel.com"},
    }


def test_browser_automation_request_still_uses_agent_browser_task():
    request = _tool_input_for_direct_call("skill:agent_browser", "打开vercel网站并截图")

    assert request["action"] == "browser.task"
    assert request["args"]["start_url"] == "https://vercel.com"
