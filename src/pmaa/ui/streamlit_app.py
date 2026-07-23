import json
from dataclasses import replace
from importlib import reload
from datetime import UTC, datetime
from html import escape

import streamlit as st
import streamlit.components.v1 as components

# Streamlit hot-reloads the page module but may retain imported helper modules.
# Reload the tightly coupled Wiki modules together so a new page call never
# targets an older renderer/service API after a code update.
import pmaa.wiki.importer as _wiki_importer_module
import pmaa.ui.wiki_render as _wiki_render_module

_wiki_importer_module = reload(_wiki_importer_module)
_wiki_render_module = reload(_wiki_render_module)

from pmaa.storage.history_store import SQLiteTaskHistoryStore
from pmaa.storage.memory_store import SQLiteMemoryStore
from pmaa.config import load_settings
from pmaa.skills.registry import SkillImportResult
from pmaa.skills.registry import LocalSkillRegistry
from pmaa.skills.runtime import SkillRuntimeInstaller, SkillRuntimeInspector
from pmaa.skills.tool_binding import SkillToolBindingService
from pmaa.ui.action_audit import append_action_audit, build_action_audit_markdown
from pmaa.ui.chat_render import (
    build_policy_card_markdown,
    build_thought_text,
    normalize_markdown_content,
    render_user_message,
)
from pmaa.ui.api_client import (
    WorkflowAPIError,
    confirm_action_via_api,
    create_daily_brief_schedule_via_api,
    create_interest_topic_via_api,
    create_monitor_rule_via_api,
    delete_interest_topic_via_api,
    delete_daily_brief_schedule_via_api,
    delete_monitor_rule_via_api,
    get_background_job_via_api,
    get_monitor_latest_result_via_api,
    get_automation_status_via_api,
    get_notification_unread_count_via_api,
    list_monitor_rules_via_api,
    list_daily_brief_schedules_via_api,
    list_interest_topics_via_api,
    list_background_jobs_via_api,
    list_notifications_via_api,
    mark_all_notifications_read_via_api,
    mark_notification_read_via_api,
    run_monitor_rule_via_api,
    run_daily_brief_now_via_api,
    submit_multi_agent_job_via_api,
    update_monitor_rule_via_api,
    update_interest_topic_selection_via_api,
    update_daily_brief_schedule_by_id_via_api,
)
from pmaa.ui.conversation_context import build_conversation_context
from pmaa.ui.export import build_bulk_markdown_export
from pmaa.ui.message_state import message_has_pending_confirmation
from pmaa.ui.view_model import build_task_view
from pmaa.ui.wiki_render import DEFAULT_GRAPH_VIEWPORT_HEIGHT, build_wiki_graph_html
from pmaa.tools.email_tool import EmailTool
from pmaa.wiki.jobs import (
    get_wiki_import_job,
    start_gbrain_skill_enrichment_job,
    start_semantic_knowledge_model_job,
    start_wiki_commit_job,
    start_wiki_delete_source_job,
    start_wiki_preview_job,
)
from pmaa.wiki.importer import (
    WikiGraph,
    WikiGraphEdge,
    WikiGraphNode,
    create_gbrain_wiki_service,
)
from pmaa.workflow.state import WorkflowResult


DEFAULT_GBRAIN_INBOX_DIR = r"C:\Users\lzl\GbrainInbox"


st.set_page_config(page_title="PMAA", page_icon="P", layout="wide")

st.markdown(
    """
    <style>
    :root {
        --bg: #f7f4ed;
        --panel: #fffdf8;
        --line: #e4dccd;
        --text: #26231d;
        --muted: #82796b;
        --gold: #b9963c;
        --gold-soft: #f3ead4;
        --green: #45b96b;
        --blue: #1f6fb2;
    }
    .stApp { background: var(--bg); color: var(--text); }
    header[data-testid="stHeader"] { background: transparent; height: 0; }
    #MainMenu, footer { visibility: hidden; }
    .block-container {
        max-width: none !important;
        width: 100% !important;
        padding: 14px 18px 18px 18px !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--line) !important;
        border-radius: 8px !important;
        background: var(--panel) !important;
        min-height: calc(100vh - 96px);
    }
    .topbar {
        height: 54px;
        border: 1px solid var(--line);
        background: rgba(255, 253, 248, 0.98);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 14px;
        margin-bottom: 10px;
    }
    .top-left, .top-center, .top-right { display: flex; align-items: center; gap: 10px; }
    .mode-pill {
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 7px 11px;
        font-size: 13px;
        font-weight: 700;
        color: #554d40;
        background: #fffefa;
    }
    .brand-dot {
        width: 32px;
        height: 32px;
        border-radius: 999px;
        background: var(--gold);
        color: white;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
    }
    .brand { font-size: 16px; font-weight: 850; color: var(--text); }
    .workspace-link { color: var(--gold); font-size: 13px; font-weight: 750; }
    .status-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--green);
    }
    .muted { color: var(--muted); font-size: 12px; }
    .nav-card {
        border: 1px solid var(--line);
        background: #fffefa;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 9px;
        font-weight: 800;
        color: #4b4439;
    }
    .nav-card.active { border-color: #dfc88e; color: #8a6716; background: #fffaf0; }
    .nav-sub { color: #aaa194; font-size: 11px; margin-left: 5px; font-weight: 700; }
    .section-label {
        color: #a49b8e;
        font-size: 12px;
        font-weight: 850;
        letter-spacing: .04em;
        margin: 18px 0 8px 2px;
    }
    .chat-header, .raw-header {
        height: 44px;
        border-bottom: 1px solid var(--line);
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
    }
    .chat-title, .raw-title { font-size: 15px; font-weight: 850; }
    .assistant-row, .user-row { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 14px; }
    .avatar {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: #ffffff;
        font-weight: 850;
        flex: 0 0 auto;
    }
    .avatar.assistant { background: #ff9f1c; }
    .avatar.user { background: #ff4d5a; }
    .message-card {
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffefa;
        padding: 13px 15px;
        color: #2f2b25;
        font-size: 15px;
        line-height: 1.75;
    }
    .email-body-box {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffefa;
        color: #2f2b25;
        padding: 14px 16px;
        min-height: 220px;
        white-space: pre-wrap;
        line-height: 1.75;
        font-size: 14px;
    }
    .question-card {
        width: 100%;
        border-radius: 8px;
        background: #f1f3f6;
        padding: 14px 16px;
        color: #263142;
        font-size: 15px;
        font-weight: 750;
    }
    .field-title { font-size: 14px; font-weight: 850; margin: 10px 0 6px 0; color: #51483b; }
    .readonly-box {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffefa;
        color: #2b2924;
        padding: 14px 16px;
        overflow: auto;
        line-height: 1.72;
        font-size: 14px;
    }
    .thought-box {
        max-height: 240px;
        font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }
    .answer-box {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffefa;
        padding: 18px 20px;
        line-height: 1.8;
        margin-top: 8px;
        color: #25221d;
        width: 100%;
    }
    .answer-box a { color: var(--blue); font-weight: 750; text-decoration: underline; }
    .answer-content h1, .answer-content h2, .answer-content h3 {
        color: #1f1d19;
        margin: 12px 0 8px;
        line-height: 1.25;
    }
    .answer-content p { margin: 8px 0; color: #25221d; }
    .answer-content ul { margin: 8px 0 8px 22px; }
    .answer-content li { margin: 4px 0; }
    .answer-content code {
        background: #f1eadb;
        border-radius: 4px;
        padding: 1px 4px;
        color: #7b5613;
    }
    .thought-details {
        border: 1px solid #eadfc9;
        border-radius: 8px;
        background: #fff8ea;
        margin-bottom: 14px;
        padding: 10px 12px;
    }
    .thought-details summary {
        cursor: pointer;
        color: #5b4d31;
        font-weight: 800;
    }
    .thought-details pre {
        margin: 10px 0 0;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        color: #2b2924;
        font-size: 13px;
        line-height: 1.65;
        font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
    }
    div[class*="st-key-chat_job_progress"] .stale,
    div[class*="st-key-chat_job_progress"] [data-stale="true"] {
        opacity: 1 !important;
        transition: none !important;
    }
    .policy-card {
        border: 1px solid #e7d8b8;
        border-radius: 8px;
        background: #fffdf8;
        padding: 10px 12px;
        margin-top: 10px;
        margin-bottom: 10px;
        color: #29251f;
    }
    .policy-card h4 {
        margin: 0 0 8px 0;
        color: #4c3d18;
        font-size: 14px;
    }
    .policy-card ul {
        margin: 0 0 0 18px;
        padding: 0;
    }
    .policy-card li {
        margin: 3px 0;
        color: #2c2822;
        font-size: 13px;
    }
    .readonly-box, .field-title { display: none !important; }
    div[class*="st-key-chat_input_bar"] {
        position: sticky;
        bottom: 0;
        z-index: 30;
        background: var(--panel);
        border-top: 1px solid var(--line);
        padding: 10px 0 0;
        margin-top: 14px;
    }
    div[class*="st-key-task_input"] {
        background: var(--panel);
        padding-top: 10px;
    }
    div[class*="st-key-send_task"] {
        position: sticky;
        bottom: 0;
        z-index: 31;
        background: var(--panel);
        padding-bottom: 8px;
    }
    .error-box {
        border: 1px solid #f1b8ae;
        border-radius: 8px;
        background: #fff0ed;
        color: #a93226;
        padding: 13px 15px;
        line-height: 1.7;
        font-size: 14px;
        font-weight: 700;
    }
    .token-pill {
        border-radius: 999px;
        background: var(--gold-soft);
        color: #8a6716;
        padding: 4px 8px;
        font-size: 12px;
        font-weight: 800;
    }
    .raw-label {
        display: inline-block;
        border-radius: 5px;
        background: #f1eadb;
        color: #9a7b2f;
        padding: 3px 7px;
        font-size: 11px;
        font-weight: 850;
        margin: 8px 0 5px 0;
    }
    div[data-testid="stTextArea"] textarea {
        border-radius: 8px;
        border-color: var(--line);
        background: #fffefa;
        color: var(--text);
        font-size: 14px;
        line-height: 1.65;
    }
    .stButton button {
        border-radius: 8px;
        min-height: 40px;
        font-weight: 850;
        border: 1px solid #e8dcc4;
        background: #fffaf0;
        color: #4a3e27;
    }
    div[class*="st-key-nav_panel"] {
        width: 100% !important;
        padding: 0 !important;
    }
    div[class*="st-key-nav_panel"] > div[data-testid="stVerticalBlock"] {
        gap: 8px !important;
    }
    div[class*="st-key-nav_panel"] div[data-testid="stElementContainer"] {
        width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[class*="st-key-nav_panel"] div[data-testid="stButton"] {
        width: 100% !important;
    }
    div[class*="st-key-nav_panel"] button {
        width: 100% !important;
        min-height: 46px !important;
        justify-content: flex-start !important;
        padding: 12px !important;
        border-radius: 8px !important;
        background: #fffefa !important;
        border: 1px solid var(--line) !important;
        color: #4b4439 !important;
        box-shadow: none !important;
    }
    div[class*="st-key-nav_panel"] button:hover {
        background: #fffaf0 !important;
        border-color: #dfc88e !important;
        color: #8a6716 !important;
    }
    div[class*="st-key-nav_"] {
        width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[class*="st-key-nav_"] div[data-testid="stButton"] {
        width: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[class*="st-key-nav_"] button {
        width: 100% !important;
        min-height: 46px !important;
        justify-content: flex-start !important;
        padding: 12px !important;
        border-radius: 8px !important;
        background: #fffefa !important;
        border: 1px solid var(--line) !important;
        color: #4b4439 !important;
        box-shadow: none !important;
    }
    div[class*="st-key-nav_"] button:hover {
        background: #fffaf0 !important;
        border-color: #dfc88e !important;
        color: #8a6716 !important;
    }
    .stButton button[kind="primary"] { background: var(--gold); border-color: var(--gold); color: #fff; }
    div[class*="st-key-recent_row_"] {
        border: 1px solid #e8dcc4;
        border-radius: 8px;
        background: #fffaf0;
        padding: 2px 6px;
        margin: 0;
        min-height: 36px;
        transition: background .14s ease, border-color .14s ease, box-shadow .14s ease;
    }
    div[data-testid="stVerticalBlock"][class*="st-key-recent_list"] {
        gap: 4px !important;
        max-height: 360px;
        overflow-y: auto;
        overflow-x: hidden;
        padding-right: 4px;
        scrollbar-gutter: stable;
    }
    div[data-testid="stVerticalBlock"][class*="st-key-recent_list"]::-webkit-scrollbar {
        width: 8px;
    }
    div[data-testid="stVerticalBlock"][class*="st-key-recent_list"]::-webkit-scrollbar-track {
        background: rgba(232, 220, 196, .35);
        border-radius: 999px;
    }
    div[data-testid="stVerticalBlock"][class*="st-key-recent_list"]::-webkit-scrollbar-thumb {
        background: #d2bf92;
        border-radius: 999px;
    }
    div[data-testid="stVerticalBlock"][class*="st-key-recent_list"]::-webkit-scrollbar-thumb:hover {
        background: #b9963c;
    }
    div[data-testid="stVerticalBlock"][class*="st-key-recent_list"] > div[data-testid="stLayoutWrapper"] {
        margin: 0 !important;
        padding: 0 !important;
    }
    div[class*="st-key-recent_list"] div[data-testid="stElementContainer"]:has(div[class*="st-key-recent_row_"]) {
        margin: 0 !important;
        padding: 0 !important;
    }
    div[class*="st-key-recent_row_"] div[data-testid="stHorizontalBlock"] {
        align-items: center !important;
        gap: 4px !important;
    }
    div[class*="st-key-recent_row_"] div[data-testid="column"] {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        min-height: 30px !important;
    }
    div[class*="st-key-recent_row_"] div[data-testid="stVerticalBlock"],
    div[class*="st-key-recent_row_"] div[data-testid="stElementContainer"] {
        gap: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[class*="st-key-recent_row_"]:hover {
        background: #fff6e7;
        border-color: #dfc88e;
        box-shadow: 0 2px 8px rgba(110, 84, 28, .06);
    }
    .history-icon {
        width: 22px;
        height: 22px;
        border-radius: 999px;
        border: 1px solid #d8d3cb;
        background: #fffdf8;
        position: relative;
        margin: 0 auto;
    }
    .history-icon::before {
        content: "";
        position: absolute;
        left: 6px;
        top: 7px;
        width: 8px;
        height: 5px;
        border: 1px solid #9c958b;
        border-radius: 5px;
    }
    .history-icon::after {
        content: "";
        position: absolute;
        left: 9px;
        top: 12px;
        width: 4px;
        height: 4px;
        border-left: 1px solid #9c958b;
        border-bottom: 1px solid #9c958b;
        transform: skew(-18deg);
        background: #fffdf8;
    }
    div[class*="st-key-history_"] button {
        justify-content: center;
        text-align: center;
        min-height: 30px;
        height: 30px;
        padding: 0 6px;
        border: 0;
        background: transparent;
        color: #151515;
        box-shadow: none;
        font-size: 15px;
        font-weight: 700;
    }
    div[class*="st-key-history_"] button p {
        width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    div[class*="st-key-history_"] button:hover,
    div[class*="st-key-history_"] button:focus {
        border: 0;
        background: transparent;
        color: #151515;
        box-shadow: none;
    }
    div[class*="st-key-recent_row_"] div[data-testid="stButton"] {
        margin: 0 !important;
        padding: 0 !important;
        width: 100%;
    }
    div[class*="st-key-recent_row_"] div[data-testid="stPopover"] {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        height: 28px !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    div[class*="st-key-actions_"] button {
        opacity: 0;
        width: 28px;
        min-width: 28px;
        height: 28px;
        min-height: 28px;
        padding: 0;
        border: 0;
        border-radius: 8px;
        background: transparent;
        color: #6f6a62;
        box-shadow: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        line-height: 1;
        transition: opacity .12s ease, background .12s ease;
    }
    div[class*="st-key-recent_row_"]:hover div[class*="st-key-actions_"] button,
    div[class*="st-key-actions_"] button:focus {
        opacity: 1;
    }
    div[class*="st-key-actions_"] button:hover {
        background: #efe4cc;
        border: 0;
        color: #2f2b25;
    }
    div[data-testid="stPopoverBody"] {
        min-width: 190px;
        padding: 12px;
        border-radius: 12px;
        border: 1px solid #e7e2da;
        box-shadow: 0 16px 40px rgba(28, 24, 18, .14);
        background: #fffdf8;
    }
    div[data-testid="stPopoverBody"] .stButton button {
        justify-content: flex-start;
        min-height: 38px;
        border: 0;
        background: transparent;
        color: #23201b;
        font-weight: 700;
        box-shadow: none;
    }
    div[data-testid="stPopoverBody"] .stButton button:hover {
        background: #f2f0eb;
        border: 0;
        color: #23201b;
    }
    div[class*="st-key-delete_"] button,
    div[class*="st-key-delete_"] button:hover {
        color: #ff4d4f !important;
    }
    div[data-testid="stPopoverBody"] div[data-testid="stTextInput"] input {
        border: 0;
        border-radius: 8px;
        background: #f0f1f4;
        color: #24211c;
        min-height: 40px;
    }
    .wiki-hero {
        border: 1px solid #d6e9df;
        border-radius: 8px;
        background: #fbfff9;
        padding: 18px;
        margin-bottom: 14px;
    }
    .wiki-kicker {
        color: #0f8b7f;
        font-size: 12px;
        font-weight: 850;
        letter-spacing: .08em;
        margin-bottom: 6px;
    }
    .wiki-title {
        color: #25221d;
        font-size: 28px;
        font-weight: 900;
        line-height: 1.2;
    }
    .wiki-desc {
        color: #6f675b;
        font-size: 13px;
        line-height: 1.7;
        margin-top: 8px;
    }
    .wiki-stat-card {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffefa;
        padding: 12px 14px;
    }
    .wiki-stat-value {
        color: #26231d;
        font-size: 24px;
        font-weight: 900;
    }
    .wiki-stat-label {
        color: #8f8578;
        font-size: 12px;
        font-weight: 800;
    }
    .wiki-graph-card {
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffefa;
        padding: 12px;
        overflow: auto;
        max-height: 820px;
    }
    .wiki-graph-hint {
        position: sticky;
        left: 0;
        top: 0;
        width: fit-content;
        border-radius: 999px;
        background: #eff8f4;
        color: #0f7a70;
        padding: 5px 10px;
        margin-bottom: 8px;
        font-size: 12px;
        font-weight: 850;
        z-index: 2;
    }
    .wiki-graph-card svg {
        width: max-content;
        min-width: 100%;
        height: auto;
        min-height: 620px;
        display: block;
        background:
            radial-gradient(circle at 30% 35%, rgba(15, 139, 127, .06), transparent 26%),
            #fffefa;
    }
    .wiki-edge-link line {
        stroke: rgba(91, 82, 68, .18);
        stroke-width: 1.1;
        cursor: pointer;
        transition: stroke .12s ease, stroke-width .12s ease;
    }
    .wiki-edge-link:hover line,
    .wiki-edge-link:focus line {
        stroke: #0f8b7f;
        stroke-width: 2.4;
    }
    .wiki-edge-link.wiki-edge-import line {
        stroke: #ef4444 !important;
        stroke-width: 1.1px !important;
        opacity: .85 !important;
    }
    .wiki-node text {
        font-size: 11px;
        font-weight: 750;
        fill: #423b31;
    }
    .wiki-node circle {
        stroke: #fffefa;
        stroke-width: 1.8;
    }
    .wiki-node-highlighted .wiki-node-core {
        fill: #ef4444 !important;
        stroke: #7f1d1d !important;
        stroke-width: 2.2px !important;
    }
    .wiki-node-highlighted text {
        fill: #b91c1c !important;
        font-weight: 900 !important;
    }
    .wiki-edge-details {
        position: sticky;
        left: 0;
        bottom: 0;
        max-width: 760px;
        margin-top: 10px;
    }
    .wiki-edge-detail {
        display: none;
        border: 1px solid #d6e9df;
        border-radius: 8px;
        background: #fbfff9;
        color: #2b2924;
        padding: 10px 12px;
        line-height: 1.7;
        font-size: 13px;
    }
    .wiki-edge-detail:first-child {
        display: block;
    }
    .wiki-edge-details:has(.wiki-edge-detail:target) .wiki-edge-detail {
        display: none;
    }
    .wiki-edge-detail:target {
        display: block;
        box-shadow: 0 10px 28px rgba(15, 139, 127, .12);
    }
    .wiki-edge-detail-title {
        color: #0f7a70;
        font-weight: 900;
        margin-bottom: 4px;
    }
    .wiki-empty-graph {
        border: 1px dashed #d8d0c3;
        border-radius: 8px;
        background: #fffefa;
        color: #8f8578;
        padding: 36px;
        text-align: center;
        font-weight: 800;
    }
    .wiki-page-pill {
        display: inline-block;
        border: 1px solid #e5dac5;
        border-radius: 999px;
        padding: 4px 8px;
        margin: 3px 4px 3px 0;
        background: #fffaf0;
        color: #5d503d;
        font-size: 12px;
        font-weight: 750;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


EXAMPLES = [
    "帮我研究 LangGraph 的核心概念，并生成学习路线",
    "对比 LangGraph、CrewAI、AutoGen 的适用场景",
    "帮我制定一个 7 天 LLM Agent 学习计划",
]

HISTORY_STORE = SQLiteTaskHistoryStore()
MEMORY_STORE = SQLiteMemoryStore()
SKILL_REGISTRY = LocalSkillRegistry()
SKILL_RUNTIME_INSPECTOR = SkillRuntimeInspector()
SKILL_RUNTIME_INSTALLER = SkillRuntimeInstaller()
SKILL_TOOL_BINDING_SERVICE = SkillToolBindingService()

if "task_input" not in st.session_state:
    st.session_state.task_input = ""
if "task_view" not in st.session_state:
    st.session_state.task_view = None
if "last_task" not in st.session_state:
    st.session_state.last_task = "新对话"
if "current_task_id" not in st.session_state:
    draft_record = HISTORY_STORE.create_draft(st.session_state.task_input)
    st.session_state.current_task_id = draft_record.task_id
    st.session_state.last_task = draft_record.title
if "running_task" not in st.session_state:
    st.session_state.running_task = ""
if "task_error" not in st.session_state:
    st.session_state.task_error = ""
if "pending_task_input" not in st.session_state:
    st.session_state.pending_task_input = ""
if "task_input_key" not in st.session_state:
    st.session_state.task_input_key = 0
if "stream_request" not in st.session_state:
    st.session_state.stream_request = None
if "active_page" not in st.session_state:
    st.session_state.active_page = "chat"
if "wiki_preview" not in st.session_state:
    st.session_state.wiki_preview = None
if "wiki_import_result" not in st.session_state:
    st.session_state.wiki_import_result = None
if "wiki_delete_result" not in st.session_state:
    st.session_state.wiki_delete_result = None
if "wiki_error" not in st.session_state:
    st.session_state.wiki_error = ""
if "wiki_import_job_id" not in st.session_state:
    st.session_state.wiki_import_job_id = ""
if "wiki_overview_graph" not in st.session_state:
    st.session_state.wiki_overview_graph = None
if "wiki_overview_highlights" not in st.session_state:
    st.session_state.wiki_overview_highlights = set()
if "wiki_overview_refresh_needed" not in st.session_state:
    st.session_state.wiki_overview_refresh_needed = True
if "email_last_result" not in st.session_state:
    st.session_state.email_last_result = None
if "email_pending_confirmation" not in st.session_state:
    st.session_state.email_pending_confirmation = {}
if "email_confirmation_result" not in st.session_state:
    st.session_state.email_confirmation_result = None
if "email_error" not in st.session_state:
    st.session_state.email_error = ""
if "email_to" not in st.session_state:
    st.session_state.email_to = ""
if "email_subject" not in st.session_state:
    st.session_state.email_subject = ""
if "email_body" not in st.session_state:
    st.session_state.email_body = ""
if "email_selected_message_id" not in st.session_state:
    st.session_state.email_selected_message_id = ""
if "email_selected_message_detail" not in st.session_state:
    st.session_state.email_selected_message_detail = None
if "email_unread_refresh_nonce" not in st.session_state:
    st.session_state.email_unread_refresh_nonce = 0
if "monitor_error" not in st.session_state:
    st.session_state.monitor_error = ""
if "monitor_notice" not in st.session_state:
    st.session_state.monitor_notice = ""
if "monitor_active_runs" not in st.session_state:
    st.session_state.monitor_active_runs = {}
if "monitor_expanded_result_rule_ids" not in st.session_state:
    st.session_state.monitor_expanded_result_rule_ids = set()
if "daily_brief_error" not in st.session_state:
    st.session_state.daily_brief_error = ""
if "daily_brief_notice" not in st.session_state:
    st.session_state.daily_brief_notice = ""
if "daily_brief_result" not in st.session_state:
    st.session_state.daily_brief_result = None
if "daily_brief_job_id" not in st.session_state:
    st.session_state.daily_brief_job_id = ""
if "email_unread_last_count" not in st.session_state:
    st.session_state.email_unread_last_count = None
if "email_last_list_filter" not in st.session_state:
    st.session_state.email_last_list_filter = None


def build_bulk_export_filename() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"pmaa_task_reports_{timestamp}.md"


def is_gbrain_enabled_setting(current_settings) -> bool:
    return bool(getattr(current_settings, "gbrain_mcp_enabled", False))


def get_gbrain_inbox_dir_setting(current_settings) -> str:
    return str(getattr(current_settings, "gbrain_inbox_dir", DEFAULT_GBRAIN_INBOX_DIR))


def wiki_node_label(graph, node_id: str) -> str:
    for node in graph.nodes:
        if node.node_id == node_id:
            return node.label
    return node_id


def refresh_wiki_overview() -> WikiGraph | None:
    try:
        graph = create_gbrain_wiki_service().overview()
    except Exception as exc:
        st.session_state.wiki_error = str(exc)
        return st.session_state.get("wiki_overview_graph")
    st.session_state.wiki_overview_graph = graph
    st.session_state.wiki_overview_refresh_needed = False
    return graph


def overlay_wiki_graph(base: WikiGraph | None, preview: WikiGraph | None) -> WikiGraph:
    """Show persisted knowledge plus, before commit, the proposed import layer."""
    nodes: dict[str, WikiGraphNode] = {
        node.node_id: node for node in (base.nodes if base else [])
    }
    edges: dict[tuple[str, str, str], WikiGraphEdge] = {
        (edge.source, edge.target, edge.edge_type): edge
        for edge in (base.edges if base else [])
    }
    if preview:
        for node in preview.nodes:
            nodes[node.node_id] = replace(node, highlighted=True)
        for edge in preview.edges:
            edges[(edge.source, edge.target, edge.edge_type)] = edge
    return WikiGraph(nodes=list(nodes.values()), edges=list(edges.values()))


def render_wiki_graph(
    graph: WikiGraph,
    highlighted_node_ids: set[str] | None = None,
) -> None:
    components.html(
        build_wiki_graph_html(graph, highlighted_node_ids=highlighted_node_ids),
        height=DEFAULT_GRAPH_VIEWPORT_HEIGHT + 170,
        scrolling=False,
    )


def sync_wiki_import_job():
    """Bring a completed process-wide Wiki job back into this UI session."""
    job = get_wiki_import_job(st.session_state.get("wiki_import_job_id"))
    if job is None:
        return None
    if job.state in {"queued", "running"}:
        return job

    st.session_state.wiki_import_job_id = ""
    if job.state == "failed":
        st.session_state.wiki_error = job.error or "GBrain Wiki 后台任务失败。"
        return job

    st.session_state.wiki_error = ""
    if job.kind == "preview":
        st.session_state.wiki_preview = job.result
        st.session_state.wiki_import_result = None
    elif job.kind == "commit":
        st.session_state.wiki_import_result = job.result
        st.session_state.wiki_delete_result = None
        st.session_state.wiki_overview_highlights = set(job.result.written_slugs)
        st.session_state.wiki_overview_refresh_needed = True
    elif job.kind == "delete":
        st.session_state.wiki_delete_result = job.result
        st.session_state.wiki_import_result = None
        st.session_state.wiki_skill_result = None
        st.session_state.wiki_semantic_result = None
        st.session_state.wiki_preview = None
        st.session_state.wiki_overview_highlights = set()
        st.session_state.wiki_overview_refresh_needed = True
    elif job.kind == "enrich":
        st.session_state.wiki_skill_result = job.result
        st.session_state.wiki_overview_highlights = {
            job.result.root_slug,
            *job.result.entity_pages,
        }
        st.session_state.wiki_overview_refresh_needed = True
    else:
        st.session_state.wiki_semantic_result = job.result
        st.session_state.wiki_overview_highlights = {
            job.result.root_slug,
            *job.result.pages,
        }
        st.session_state.wiki_overview_refresh_needed = True
    return job


@st.fragment(run_every=2)
def render_wiki_job_watcher() -> None:
    """Poll only the small job-status fragment while a background import runs."""
    job = get_wiki_import_job(st.session_state.get("wiki_import_job_id"))
    if job is None:
        return
    if job.state in {"queued", "running"}:
        action = {
            "preview": "准备原生来源导入",
            "commit": "写入 GBrain 原生来源页",
            "delete": "删除 GBrain 来源页及相关知识",
            "enrich": "按 GBrain 官方 Skill 整理来源页",
            "semantic_model": "建立语义知识模型",
        }[job.kind]
        st.info(f"正在后台{action}，完成后会自动显示结果；你可以自由切换页面。")
        return
    sync_wiki_import_job()
    st.rerun(scope="app")


def resolve_pending_confirmation(approved: bool) -> None:
    view = st.session_state.get("task_view") or {}
    pending_confirmation = view.get("pending_confirmation") or {}
    if not pending_confirmation:
        return
    confirmation_result = confirm_action_via_api(
        pending_confirmation,
        approved=approved,
    )
    answer = build_action_audit_markdown(confirmation_result)
    audited_view = append_action_audit(view, confirmation_result)
    updated_view = {
        **audited_view,
        "answer": answer,
        "pending_confirmation": {},
        "confirmation_result": confirmation_result,
        "metrics": {
            **view.get("metrics", {}),
            "reflection_status": "已批准" if approved else "已拒绝",
        },
    }
    st.session_state.task_view = updated_view
    task_id = st.session_state.get("current_task_id")
    if task_id:
        HISTORY_STORE.replace_view(task_id, updated_view)


def render_answer_or_confirmation(view: dict) -> None:
    pending_confirmation = view.get("pending_confirmation") or {}
    if pending_confirmation:
        action = pending_confirmation.get("action", "")
        permission_level = pending_confirmation.get("permission_level", "")
        plan = pending_confirmation.get("plan", {})
        st.markdown("### 等待用户确认")
        st.warning(f"请求执行 `{action}`，权限级别：`{permission_level}`。")
        if plan:
            st.json(plan)
        st.caption("点击允许后才会执行该动作；拒绝则不会执行任何外部操作。")
        approve_col, reject_col = st.columns(2)
        with approve_col:
            if st.button("允许", type="primary", use_container_width=True, key="approve_pending_action"):
                resolve_pending_confirmation(True)
                st.rerun()
        with reject_col:
            if st.button("拒绝", use_container_width=True, key="reject_pending_action"):
                resolve_pending_confirmation(False)
                st.rerun()
        return
    st.markdown(view["answer"])
    source_references = view.get("source_references") or []
    if not source_references:
        return
    with st.expander(f"检索证据与溯源（{len(source_references)} 条）", expanded=False):
        st.caption("回答中的 [S1]、[S2] 与下方证据卡片一一对应。这里展示实际命中的 Wiki 页面、原始导入文档和分块原文。")
        for reference in source_references:
            st.markdown(f"#### {reference.get('label', '资料来源')}")
            document_title = reference.get("document_title") or reference.get("document_filename")
            if document_title:
                st.markdown(f"**原始文档**：{document_title}")
            if reference.get("document_filename") and reference.get("document_filename") != document_title:
                st.caption(f"文件名：{reference['document_filename']}")
            page_slug = reference.get("page_slug") or reference.get("url", "").removeprefix("gbrain://page/")
            if page_slug:
                st.caption(f"Wiki 页面：`{page_slug}`")
            chunk_index = reference.get("chunk_index")
            chunk_label = f"命中分块：第 {chunk_index + 1} 段" if isinstance(chunk_index, int) else "命中分块：页面摘要"
            score = reference.get("score")
            if isinstance(score, (int, float)):
                chunk_label += f" · 相关度：{score:.3f}"
            st.caption(chunk_label)
            st.markdown("**命中原文片段**")
            st.code(reference.get("snippet") or "（未返回片段）", language="markdown")
            if reference.get("document_path"):
                st.caption(f"Inbox 原文件：`{reference['document_path']}`")


def build_raw_context(view: dict | None, task_input: str) -> str:
    parts = [
        "SYSTEM\n任务入口、路由和最终汇总\n生成结构化执行计划\n检索外部资料来源\n生成结构化回答\n检查回答质量",
        f"USER\n{task_input}",
    ]
    if view is None:
        parts.append("ASSISTANT\n等待运行工作流。")
    else:
        for event in view["events"]:
            payload = json.dumps(event["output"], ensure_ascii=False, indent=2)
            parts.append(f"{event['label'].upper()}\n{payload}")
    return "\n\n".join(parts)


AGENT_LABELS = {
    "supervisor": "Supervisor",
    "knowledge": "Knowledge",
    "email": "Email",
    "planner": "Planner",
    "search": "Search",
    "tool": "Tool",
    "writer": "Writer",
    "reflection": "Reflection",
}


def build_live_view(events: list[dict], answer: str = "") -> dict:
    unique_agents = {
        event["agent"]
        for event in events
        if event["agent"] in AGENT_LABELS
    }
    return {
        "status": "running",
        "answer": answer,
        "sources": [],
        "source_references": [],
        "reflection": {"passed": False, "issues": []},
        "metrics": {
            "agent_count": len(unique_agents),
            "source_count": 0,
            "reflection_status": "running",
            "llm_model": "",
        },
        "events": events,
    }


def call_email_tool(payload: dict) -> dict:
    try:
        result = EmailTool().__call__(payload)
    except Exception as exc:
        st.session_state.email_error = str(exc)
        return {}
    st.session_state.email_error = ""
    action = result.get("action", payload.get("action", ""))
    if action == "list_recent":
        st.session_state.email_last_result = result
        st.session_state.email_selected_message_detail = None
        refresh_email_unread_badge()
    elif action == "get_message":
        st.session_state.email_selected_message_detail = result
        if result.get("message") and payload.get("mark_read"):
            sync_read_message_in_email_list(str(result["message"].get("message_id", "")))
            refresh_email_unread_badge()
            if "email_list_limit" in st.session_state and "email_unread_only_filter" in st.session_state:
                st.session_state.email_last_list_filter = (
                    int(st.session_state.email_list_limit),
                    bool(st.session_state.email_unread_only_filter),
                )
    if result.get("status") == "confirmation_required":
        st.session_state.email_pending_confirmation = result
    return result


def sync_read_message_in_email_list(message_id: str) -> None:
    if not message_id:
        return
    last_result = st.session_state.get("email_last_result")
    if not last_result:
        return
    messages = last_result.get("messages") or []
    next_messages = []
    for message in messages:
        if str(message.get("message_id", "")) == message_id:
            message = {**message, "unread": False}
        next_messages.append(message)
    st.session_state.email_last_result = {**last_result, "messages": next_messages}


def refresh_email_unread_badge() -> None:
    st.session_state.email_unread_refresh_nonce += 1
    get_email_unread_count.clear()


@st.cache_data(ttl=60, show_spinner=False)
def get_email_unread_count(refresh_nonce: int = 0) -> tuple[int, str]:
    current_settings = load_settings()
    if not current_settings.qq_email_address or not current_settings.qq_email_auth_code:
        return 0, "missing_config"
    try:
        result = EmailTool().__call__({"action": "count_today_unread"})
    except Exception as exc:
        return 0, str(exc)
    if result.get("status") == "configuration_error":
        return 0, result.get("answer", "missing_config")
    return int(result.get("unread_count") or 0), ""


def render_email_nav_badge_style(count: int) -> None:
    if count <= 0:
        st.markdown(
            """
            <style>
            .st-key-nav_email button::after {
                content: none !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        return
    label = "99+" if count > 99 else str(count)
    st.markdown(
        f"""
        <style>
        .st-key-nav_email button {{
            position: relative;
            padding-right: 48px !important;
        }}
        .st-key-nav_email button::after {{
            content: "{label}";
            position: absolute;
            right: 14px;
            top: 50%;
            transform: translateY(-50%);
            min-width: 22px;
            height: 22px;
            padding: 0 7px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            background: #e5484d;
            color: #fff;
            font-size: 12px;
            font-weight: 850;
            line-height: 22px;
            box-shadow: 0 2px 8px rgba(229, 72, 77, .28);
            box-sizing: border-box;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_notification_nav_badge_style(button_key: str, count: int) -> None:
    label = "99+" if count > 99 else str(count)
    content = f'"{label}"' if count > 0 else "none"
    st.markdown(
        f"""
        <style>
        .st-key-{button_key} button {{
            position: relative;
            padding-right: 48px !important;
        }}
        .st-key-{button_key} button::after {{
            content: {content};
            position: absolute;
            right: 14px;
            top: 50%;
            transform: translateY(-50%);
            min-width: 22px;
            height: 22px;
            padding: 0 7px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            background: #e5484d;
            color: #fff;
            font-size: 12px;
            font-weight: 850;
            line-height: 22px;
            box-shadow: 0 2px 8px rgba(229, 72, 77, .28);
            box-sizing: border-box;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every="10s")
def render_notification_nav_button(
    *,
    kind: str,
    label: str,
    page: str,
    button_key: str,
) -> None:
    count = get_notification_unread_count_via_api(kind=kind)
    render_notification_nav_badge_style(button_key, count)
    if st.button(label, key=button_key, use_container_width=True):
        st.session_state.active_page = page
        st.rerun(scope="app")


@st.fragment(run_every="60s")
def render_email_nav_button() -> None:
    count, error = get_email_unread_count(st.session_state.email_unread_refresh_nonce)
    last_count = st.session_state.get("email_unread_last_count")
    if count > 0 and (last_count is None or count > last_count):
        st.toast(f"你有 {count} 封未读邮件。")
    st.session_state.email_unread_last_count = count
    render_email_nav_badge_style(count)
    if st.button("邮件助手  QQ Mail", key="nav_email", use_container_width=True):
        st.session_state.active_page = "email"
        st.rerun(scope="app")
    if error and error != "missing_config":
        st.caption("邮箱未读检查失败")


def resolve_email_pending_confirmation(approved: bool) -> None:
    pending_confirmation = st.session_state.get("email_pending_confirmation") or {}
    if not pending_confirmation:
        return
    confirmation_result = confirm_action_via_api(
        pending_confirmation,
        approved=approved,
    )
    st.session_state.email_confirmation_result = confirmation_result
    st.session_state.email_pending_confirmation = {}


def render_email_messages(result: dict | None) -> None:
    if not result:
        st.info("点击上方按钮读取最近邮件。")
        return
    if result.get("status") == "configuration_error":
        st.error(result.get("answer", "邮箱配置不完整。"))
        return
    messages = result.get("messages") or []
    if not messages:
        st.markdown(result.get("answer", "暂无邮件。"))
        return
    for index, message in enumerate(messages, start=1):
        with st.container(border=True):
            unread_label = "未读" if message.get("unread") else "已读"
            st.markdown(f"**{index}. {message.get('subject') or '无主题'}** · `{unread_label}`")
            st.caption(f"发件人：{message.get('from_addr', '')}")
            st.caption(f"时间：{message.get('date', '')}")
            st.write(message.get("snippet", ""))
            message_id = str(message.get("message_id", ""))
            select_col, detail_col = st.columns(2)
            with select_col:
                if st.button("选择用于回复", key=f"email_select_{message_id}", use_container_width=True):
                    st.session_state.email_selected_message_id = message_id
                    st.rerun()
            with detail_col:
                if st.button("查看全文", key=f"email_detail_{message_id}", use_container_width=True):
                    st.session_state.email_selected_message_id = message_id
                    call_email_tool(
                        {
                            "action": "get_message",
                            "message_id": st.session_state.email_selected_message_id,
                            "mark_read": True,
                        }
                    )
                    st.rerun()
            detail_result = st.session_state.get("email_selected_message_detail")
            selected_id = st.session_state.get("email_selected_message_id")
            if selected_id == message_id and detail_result:
                detail_message = detail_result.get("message")
                with st.expander("邮件全文", expanded=True):
                    if detail_message:
                        st.markdown(f"**{detail_message.get('subject') or '无主题'}**")
                        st.caption(f"发件人：{detail_message.get('from_addr', '')}")
                        st.caption(f"时间：{detail_message.get('date', '')}")
                        body_text = detail_message.get("body") or detail_message.get("snippet") or ""
                        st.markdown(
                            f'<div class="email-body-box">{escape(body_text)}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.warning(detail_result.get("answer", "没有读取到这封邮件的全文。"))


def render_email_pending_confirmation() -> None:
    pending_confirmation = st.session_state.get("email_pending_confirmation") or {}
    if not pending_confirmation:
        return
    plan = pending_confirmation.get("plan", {})
    with st.container(border=True):
        st.markdown("### 等待发送确认")
        st.warning("邮件发送属于不可撤回动作，只有点击允许后才会真正通过 SMTP 发出。")
        st.markdown(f"**收件人**：`{plan.get('to', '')}`")
        st.markdown(f"**主题**：{plan.get('subject', '')}")
        st.text_area(
            "待发送正文",
            value=plan.get("body", ""),
            height=180,
            disabled=True,
            key="email_pending_body_preview",
        )
        approve_col, reject_col = st.columns(2)
        with approve_col:
            if st.button("允许发送", type="primary", use_container_width=True, key="email_approve_send"):
                resolve_email_pending_confirmation(True)
                st.rerun()
        with reject_col:
            if st.button("拒绝发送", use_container_width=True, key="email_reject_send"):
                resolve_email_pending_confirmation(False)
                st.rerun()


def render_email_assistant_page() -> None:
    current_settings = load_settings()
    configured = bool(current_settings.qq_email_address and current_settings.qq_email_auth_code)
    st.markdown(
        """
        <div class="chat-header">
          <div class="chat-title">邮件助手 <span class="status-dot"></span></div>
          <div class="muted">QQ Mail · IMAP read · SMTP send approval</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if configured:
        st.success(f"已配置邮箱：{current_settings.qq_email_address}")
    else:
        st.warning("邮箱尚未配置。请在 .env 中填写 QQ_EMAIL_ADDRESS 和 QQ_EMAIL_AUTH_CODE 后重启服务。")

    with st.container(border=True):
        st.markdown("### 收件箱")
        limit_col, unread_col, action_col = st.columns([0.22, 0.22, 0.56])
        with limit_col:
            limit = st.number_input(
                "读取数量",
                min_value=1,
                max_value=20,
                value=5,
                step=1,
                key="email_list_limit",
            )
        with unread_col:
            unread_only = st.toggle("只看未读", value=False, key="email_unread_only_filter")
        current_filter = (int(limit), bool(unread_only))
        if (
            st.session_state.get("email_last_result") is not None
            and st.session_state.get("email_last_list_filter") != current_filter
        ):
            call_email_tool(
                {
                    "action": "list_recent",
                    "limit": int(limit),
                    "unread_only": unread_only,
                }
            )
            st.session_state.email_last_list_filter = current_filter
        with action_col:
            st.write("")
            if st.button("读取最近邮件", use_container_width=True, disabled=not configured):
                call_email_tool(
                    {
                        "action": "list_recent",
                        "limit": int(limit),
                        "unread_only": unread_only,
                    }
                )
                st.session_state.email_last_list_filter = current_filter
                st.rerun()
        render_email_messages(st.session_state.get("email_last_result"))

    with st.container(border=True):
        st.markdown("### 回复 / 写邮件")
        st.caption("页面只生成草稿或待确认发送动作；真正发送必须二次确认。")
        messages = (st.session_state.get("email_last_result") or {}).get("messages") or []
        message_options = {
            f"{index}. {message.get('subject') or '无主题'} - {message.get('from_addr', '')}": str(message.get("message_id", ""))
            for index, message in enumerate(messages, start=1)
        }
        selected_label = None
        if message_options:
            selected_label = st.selectbox(
                "选择要回复的邮件",
                options=list(message_options.keys()),
                placeholder="请先选择邮件",
                key="email_reply_source_label",
            )
        else:
            st.info("请先读取收件箱，再选择要回复的邮件。")
        if selected_label:
            st.session_state.email_selected_message_id = message_options[selected_label]
        draft_col, clear_col = st.columns([0.5, 0.5])
        with draft_col:
            selected_message_id = st.session_state.get("email_selected_message_id", "")
            if st.button("基于选中邮件生成回复草稿", use_container_width=True, disabled=not configured or not selected_message_id):
                result = call_email_tool({"action": "draft_reply", "message_id": selected_message_id})
                draft = result.get("draft") if result else None
                if draft:
                    st.session_state.email_to = draft.get("to", "")
                    st.session_state.email_subject = draft.get("subject", "")
                    st.session_state.email_body = draft.get("body", "")
                st.rerun()
        with clear_col:
            if st.button("清空草稿", use_container_width=True):
                st.session_state.email_to = ""
                st.session_state.email_subject = ""
                st.session_state.email_body = ""
                st.session_state.email_pending_confirmation = {}
                st.session_state.email_confirmation_result = None
                st.session_state.email_selected_message_id = ""
                st.session_state.email_selected_message_detail = None
                st.rerun()

        st.text_input("收件人", key="email_to", placeholder="name@example.com")
        st.text_input("主题", key="email_subject", placeholder="请输入邮件主题")
        st.text_area("正文", key="email_body", height=180, placeholder="请输入邮件正文")
        if st.button("生成发送确认", type="primary", use_container_width=True, disabled=not configured):
            call_email_tool(
                {
                    "action": "prepare_send",
                    "to": st.session_state.email_to,
                    "subject": st.session_state.email_subject,
                    "body": st.session_state.email_body,
                }
            )
            st.rerun()

    render_email_pending_confirmation()
    if st.session_state.get("email_confirmation_result"):
        with st.container(border=True):
            st.markdown("### 动作审计")
            st.markdown(build_action_audit_markdown(st.session_state.email_confirmation_result))
    if st.session_state.get("email_error"):
        st.error(st.session_state.email_error)


def render_email_trace_panel() -> None:
    current_settings = load_settings()
    st.markdown("### Email Trace")
    st.metric("Config", "Ready" if current_settings.qq_email_address and current_settings.qq_email_auth_code else "Missing")
    st.caption("授权码不会在页面中展示。")
    if st.session_state.get("email_pending_confirmation"):
        st.markdown("#### Pending Confirmation")
        st.json(st.session_state.email_pending_confirmation)
    if st.session_state.get("email_confirmation_result"):
        st.markdown("#### Last Action")
        st.json(st.session_state.email_confirmation_result)
    if st.session_state.get("email_last_result"):
        st.markdown("#### Last Result")
        st.json(st.session_state.email_last_result)


MONITOR_TARGET_LABELS = {
    "公司动态": "company",
    "招聘岗位": "jobs",
    "新闻资讯": "news",
    "GitHub 项目": "github",
    "技术博客": "tech_blog",
}


def render_daily_brief_page() -> None:
    st.markdown(
        """
        <div class="chat-header">
          <div class="chat-title">每日简报 <span class="status-dot"></span></div>
          <div class="muted">Daily Brief Agent · Email · Web Research · Calendar · Memory</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("汇总当天未读和重要邮件、关注主题新闻、今日日程与个人偏好。")

    if st.session_state.daily_brief_notice:
        st.success(st.session_state.daily_brief_notice)
        st.session_state.daily_brief_notice = ""
    if st.session_state.daily_brief_error:
        st.error(st.session_state.daily_brief_error)
        st.session_state.daily_brief_error = ""

    try:
        topics = list_interest_topics_via_api()
        schedules = list_daily_brief_schedules_via_api()
        brief_jobs = list_background_jobs_via_api(kind="daily_brief", limit=30)
    except WorkflowAPIError as exc:
        st.error(str(exc))
        return

    st.markdown("### 定时简报计划")
    with st.expander("新增简报计划"):
        with st.form("create_daily_brief_schedule_form", clear_on_submit=True):
            create_name = st.text_input("计划名称", placeholder="例如：晨间简报")
            create_time = st.time_input(
                "每天生成时间",
                value=datetime.strptime("08:00", "%H:%M").time(),
                step=900,
            )
            create_enabled = st.toggle("创建后启用", value=True)
            create_submitted = st.form_submit_button(
                "新增计划",
                use_container_width=True,
            )
        if create_submitted:
            if not create_name.strip():
                st.session_state.daily_brief_error = "计划名称不能为空。"
            else:
                try:
                    create_daily_brief_schedule_via_api(
                        {
                            "name": create_name.strip(),
                            "enabled": create_enabled,
                            "run_time": create_time.strftime("%H:%M"),
                            "timezone": "Asia/Shanghai",
                        }
                    )
                    st.session_state.daily_brief_notice = "简报计划已新增。"
                except WorkflowAPIError as exc:
                    st.session_state.daily_brief_error = str(exc)
            st.rerun()

    if not schedules:
        st.info("还没有定时简报计划，可新增多个不同时间的计划。")
    for schedule in schedules:
        schedule_id = str(schedule["schedule_id"])
        schedule_running = any(
            job.get("status") in {"pending", "running"}
            and str((job.get("request") or {}).get("metadata", {}).get("schedule_id") or "")
            == schedule_id
            for job in brief_jobs
        )
        with st.container(border=True):
            summary_col, run_col, delete_col = st.columns(
                [0.56, 0.24, 0.20],
                vertical_alignment="center",
            )
            status_text = "已启用" if schedule.get("enabled") else "已停用"
            summary_col.markdown(
                f"**{schedule.get('name', '每日简报')}**  \n"
                f"每天 `{schedule.get('run_time')}` · {status_text}"
            )
            if run_col.button(
                "立即生成",
                key=f"run_daily_brief_schedule_{schedule_id}",
                use_container_width=True,
                disabled=schedule_running,
            ):
                try:
                    job = run_daily_brief_now_via_api(schedule_id=schedule_id)
                    st.session_state.daily_brief_job_id = str(job["job_id"])
                    st.session_state.daily_brief_result = None
                    st.session_state.daily_brief_notice = "简报已提交后台生成。"
                except WorkflowAPIError as exc:
                    st.session_state.daily_brief_error = str(exc)
                st.rerun()
            if delete_col.button(
                "删除",
                key=f"delete_daily_brief_schedule_{schedule_id}",
                use_container_width=True,
            ):
                try:
                    delete_daily_brief_schedule_via_api(schedule_id)
                    st.session_state.daily_brief_notice = "简报计划已删除。"
                except WorkflowAPIError as exc:
                    st.session_state.daily_brief_error = str(exc)
                st.rerun()
            with st.expander("修改计划"):
                with st.form(f"update_daily_brief_schedule_{schedule_id}"):
                    update_name = st.text_input(
                        "计划名称",
                        value=str(schedule.get("name") or "每日简报"),
                    )
                    update_time = st.time_input(
                        "每天生成时间",
                        value=datetime.strptime(
                            str(schedule.get("run_time") or "08:00"),
                            "%H:%M",
                        ).time(),
                        step=900,
                    )
                    update_enabled = st.toggle(
                        "启用计划",
                        value=bool(schedule.get("enabled")),
                    )
                    update_submitted = st.form_submit_button(
                        "保存修改",
                        use_container_width=True,
                    )
                if update_submitted:
                    if not update_name.strip():
                        st.session_state.daily_brief_error = "计划名称不能为空。"
                    else:
                        try:
                            update_daily_brief_schedule_by_id_via_api(
                                schedule_id,
                                {
                                    "name": update_name.strip(),
                                    "enabled": update_enabled,
                                    "run_time": update_time.strftime("%H:%M"),
                                    "timezone": "Asia/Shanghai",
                                },
                            )
                            st.session_state.daily_brief_notice = "简报计划已修改。"
                        except WorkflowAPIError as exc:
                            st.session_state.daily_brief_error = str(exc)
                    st.rerun()

    st.markdown("### 简报关注主题")
    latest_brief_job = brief_jobs[0] if brief_jobs else {}
    brief_is_running = latest_brief_job.get("status") in {"pending", "running"}
    topic_by_name = {str(topic["name"]): topic for topic in topics}
    enabled_topic_key = "_".join(
        sorted(str(topic["topic_id"]) for topic in topics if topic.get("enabled"))
    )
    selected_topic_names = st.multiselect(
        "选择今天希望关注的新闻方向",
        options=list(topic_by_name),
        default=[
            name
            for name, topic in topic_by_name.items()
            if topic.get("enabled")
        ],
        placeholder="可同时选择多个主题",
        key=f"brief_interest_topic_selection_{enabled_topic_key}",
    )
    saved_topic_names = {
        name for name, topic in topic_by_name.items() if topic.get("enabled")
    }
    topic_selection_dirty = set(selected_topic_names) != saved_topic_names
    if st.button(
        "保存简报主题",
        use_container_width=True,
        key="brief_save_interest_topics",
        disabled=not topic_selection_dirty,
    ):
        try:
            update_interest_topic_selection_via_api(
                [topic_by_name[name]["topic_id"] for name in selected_topic_names]
            )
            st.session_state.daily_brief_notice = "简报主题已保存。"
        except WorkflowAPIError as exc:
            st.session_state.daily_brief_error = str(exc)
        st.rerun()

    with st.expander("添加自定义简报主题"):
        with st.form("create_brief_interest_topic_form", clear_on_submit=True):
            custom_topic_name = st.text_input(
                "主题名称",
                placeholder="例如：多模态模型",
            )
            custom_topic_query = st.text_input(
                "新闻检索重点",
                placeholder="例如：今天多模态模型的重要发布、开源项目和应用进展",
            )
            custom_topic_submitted = st.form_submit_button(
                "添加并关注",
                use_container_width=True,
            )
        if custom_topic_submitted:
            if not custom_topic_name.strip() or not custom_topic_query.strip():
                st.session_state.daily_brief_error = "主题名称和检索重点不能为空。"
            else:
                try:
                    created_topic = create_interest_topic_via_api(
                        {
                            "name": custom_topic_name.strip(),
                            "query": custom_topic_query.strip(),
                        }
                    )
                    enabled_ids = [
                        str(topic["topic_id"])
                        for topic in topics
                        if topic.get("enabled")
                    ]
                    update_interest_topic_selection_via_api(
                        [*enabled_ids, str(created_topic["topic_id"])]
                    )
                    st.session_state.daily_brief_notice = "自定义简报主题已添加。"
                except WorkflowAPIError as exc:
                    st.session_state.daily_brief_error = str(exc)
            st.rerun()

        for topic in [item for item in topics if not item.get("is_preset")]:
            detail_col, delete_col = st.columns([0.82, 0.18], vertical_alignment="center")
            detail_col.markdown(f"**{topic['name']}**  \n{topic['query']}")
            if delete_col.button(
                "删除",
                key=f"delete_brief_interest_topic_{topic['topic_id']}",
                use_container_width=True,
            ):
                try:
                    delete_interest_topic_via_api(str(topic["topic_id"]))
                    st.session_state.daily_brief_notice = "自定义简报主题已删除。"
                except WorkflowAPIError as exc:
                    st.session_state.daily_brief_error = str(exc)
                st.rerun()

    if topic_selection_dirty:
        st.caption("主题选择已修改，请先保存再生成简报。")
    if st.button(
        "生成今日简报",
        type="primary",
        use_container_width=True,
        key="generate_daily_brief",
        disabled=topic_selection_dirty or brief_is_running,
    ):
        try:
            job = run_daily_brief_now_via_api()
            st.session_state.daily_brief_job_id = str(job["job_id"])
            st.session_state.daily_brief_result = None
            st.session_state.daily_brief_notice = (
                "简报已提交后台生成，可以切换到其他页面继续使用。"
            )
        except WorkflowAPIError as exc:
            st.session_state.daily_brief_error = str(exc)
        st.rerun()

    render_daily_brief_job_status()


def render_daily_brief_job_status() -> None:
    job_id = str(st.session_state.get("daily_brief_job_id") or "")
    try:
        if job_id:
            job = get_background_job_via_api(job_id)
        else:
            jobs = list_background_jobs_via_api(kind="daily_brief", limit=1)
            job = jobs[0] if jobs else None
    except WorkflowAPIError as exc:
        st.error(str(exc))
        return
    if not job:
        st.info("还没有生成过每日简报。")
        return
    status = str(job.get("status") or "")
    if status in {"pending", "running"}:
        render_running_daily_brief_job(str(job["job_id"]))
        return
    if status == "failed":
        st.error(f"简报生成失败：{job.get('error') or '未知错误'}")
        return
    try:
        for notification in list_notifications_via_api(
            kind="daily_brief",
            unread_only=True,
            limit=100,
        ):
            metadata = notification.get("metadata") or {}
            if str(metadata.get("job_id") or "") == str(job.get("job_id") or ""):
                mark_notification_read_via_api(str(notification["notification_id"]))
                break
    except WorkflowAPIError:
        pass
    try:
        result = WorkflowResult.model_validate(job.get("result") or {})
    except Exception as exc:
        st.error(f"简报结果格式错误：{exc}")
        return
    st.session_state.daily_brief_result = result
    if result.final_result is not None:
        st.markdown("### 今日简报")
        st.caption(f"完成时间：{job.get('completed_at') or ''}")
        with st.container(border=True):
            st.markdown(normalize_markdown_content(result.final_result.answer))


@st.fragment(run_every="2s")
def render_running_daily_brief_job(job_id: str) -> None:
    try:
        job = get_background_job_via_api(job_id)
    except WorkflowAPIError as exc:
        st.error(str(exc))
        return
    status = str(job.get("status") or "")
    if status not in {"pending", "running"}:
        st.rerun(scope="app")
        return
    st.info("Daily Brief Agent 正在后台汇总邮件、新闻、日程和长期偏好。")
    events = (job.get("progress") or {}).get("events") or []
    if events:
        with st.expander("查看当前执行进度"):
            for event in events[-8:]:
                agent = str(event.get("agent") or "Agent")
                event_type = str(event.get("event_type") or "running")
                st.markdown(f"- `{agent}` · {event_type}")


def render_daily_brief_data_panel() -> None:
    current_settings = load_settings()
    try:
        topics = list_interest_topics_via_api()
        schedules = list_daily_brief_schedules_via_api()
        brief_jobs = list_background_jobs_via_api(kind="daily_brief", limit=1)
        brief_notifications = list_notifications_via_api(
            kind="daily_brief",
            limit=30,
        )
        brief_unread_count = get_notification_unread_count_via_api(kind="daily_brief")
    except WorkflowAPIError as exc:
        st.error(str(exc))
        topics = []
        schedules = []
        brief_jobs = []
        brief_notifications = []
        brief_unread_count = 0
    enabled_topics = [topic for topic in topics if topic.get("enabled")]
    enabled_memories = [memory for memory in MEMORY_STORE.list_all() if memory.enabled]
    st.markdown("### 简报数据源")
    st.metric(
        "QQ 邮箱",
        "已连接" if current_settings.qq_email_address and current_settings.qq_email_auth_code else "未配置",
    )
    st.metric("新闻主题", len(enabled_topics))
    st.metric(
        "日历",
        "已连接" if current_settings.calendar_provider != "disabled" else "未配置",
    )
    st.metric("长期记忆", len(enabled_memories))
    st.divider()
    enabled_schedules = [schedule for schedule in schedules if schedule.get("enabled")]
    st.caption(
        f"简报计划：共 {len(schedules)} 个，已启用 {len(enabled_schedules)} 个"
    )
    for schedule in enabled_schedules:
        st.markdown(f"- {schedule.get('run_time')} · {schedule.get('name')}")
    if brief_jobs:
        latest_job = brief_jobs[0]
        st.caption(
            f"最近任务：{latest_job.get('status')} · "
            f"{latest_job.get('created_at', '')}"
        )
    if enabled_topics:
        st.markdown("**当前关注**")
        for topic in enabled_topics:
            st.markdown(f"- {topic['name']}")
    st.divider()
    inbox_title_col, inbox_action_col = st.columns(
        [0.58, 0.42],
        vertical_alignment="center",
    )
    inbox_title_col.markdown("### 简报收件箱")
    if inbox_action_col.button(
        "全部已读",
        key="mark_all_daily_briefs_read",
        use_container_width=True,
        disabled=brief_unread_count == 0,
    ):
        try:
            mark_all_notifications_read_via_api(kind="daily_brief")
        except WorkflowAPIError as exc:
            st.error(str(exc))
        st.rerun()
    st.caption(f"{brief_unread_count} 条未读简报")
    if not brief_notifications:
        st.info("暂无已生成的简报。")
    for notification in brief_notifications:
        notification_id = str(notification["notification_id"])
        metadata = notification.get("metadata") or {}
        job_id = str(metadata.get("job_id") or "")
        unread_prefix = "未读 · " if not notification.get("read") else ""
        with st.container(border=True):
            st.markdown(
                f"**{unread_prefix}{notification.get('title', '每日简报')}**"
            )
            st.caption(str(notification.get("created_at") or ""))
            if st.button(
                "查看简报",
                key=f"open_daily_brief_{notification_id}",
                use_container_width=True,
                disabled=not job_id,
            ):
                try:
                    if not notification.get("read"):
                        mark_notification_read_via_api(notification_id)
                    st.session_state.daily_brief_job_id = job_id
                except WorkflowAPIError as exc:
                    st.error(str(exc))
                st.rerun()


def _monitor_run_finished(last_run_at: str | None, started_at: str) -> bool:
    if not last_run_at:
        return False
    try:
        return datetime.fromisoformat(last_run_at) >= datetime.fromisoformat(started_at)
    except ValueError:
        return last_run_at >= started_at


def render_monitor_latest_result(result: dict, *, expanded: bool = False) -> None:
    items = result.get("items") or []
    observed_at = result.get("observed_at") or result.get("last_run_at") or "尚未运行"
    label = f"最近一次运行结果 · {len(items)} 条 · {observed_at}"
    with st.expander(label, expanded=expanded):
        if not items:
            st.caption("本次尚未生成可展示的监控快照，请查看通知中心中的失败或无结果说明。")
            return
        for index, item in enumerate(items[:20], start=1):
            if not isinstance(item, dict):
                st.markdown(f"{index}. {item}")
                continue
            title = str(
                item.get("title")
                or item.get("full_name")
                or item.get("name")
                or item.get("url")
                or f"结果 {index}"
            )
            url = str(item.get("url") or item.get("html_url") or "")
            st.markdown(f"**{index}. [{title}]({url})**" if url else f"**{index}. {title}**")
            summary = str(
                item.get("snippet")
                or item.get("description")
                or item.get("summary")
                or ""
            ).strip()
            if summary:
                st.markdown(summary[:500])
            metadata = []
            if item.get("stars") is not None:
                metadata.append(f"Stars {item.get('stars')}")
            if item.get("language"):
                metadata.append(str(item.get("language")))
            if item.get("latest_release"):
                metadata.append(f"Release {item.get('latest_release')}")
            if item.get("published_at"):
                metadata.append(str(item.get("published_at")))
            if metadata:
                st.caption(" · ".join(metadata))
            if index < min(len(items), 20):
                st.divider()
        if len(items) > 20:
            st.caption(f"共 {len(items)} 条，当前展示前 20 条。")


@st.fragment(run_every="2s")
def render_monitor_active_run(rule_id: str, started_at: str) -> None:
    try:
        result = get_monitor_latest_result_via_api(rule_id)
    except WorkflowAPIError as exc:
        st.error(str(exc))
        return
    if not _monitor_run_finished(result.get("last_run_at"), started_at):
        st.info("Monitor Agent 正在检索、比较并保存监控快照，你可以切换到其他页面。")
        return
    active_runs = dict(st.session_state.get("monitor_active_runs") or {})
    active_runs.pop(rule_id, None)
    st.session_state.monitor_active_runs = active_runs
    expanded_rule_ids = set(
        st.session_state.get("monitor_expanded_result_rule_ids") or set()
    )
    expanded_rule_ids.add(rule_id)
    st.session_state.monitor_expanded_result_rule_ids = expanded_rule_ids
    st.session_state.monitor_notice = (
        f"监控运行完成，获得 {result.get('item_count', 0)} 条结果。"
    )
    st.rerun(scope="app")


def _start_monitor_runs(rules: list[dict]) -> tuple[int, list[str]]:
    active_runs = dict(st.session_state.get("monitor_active_runs") or {})
    started_count = 0
    errors: list[str] = []
    for rule in rules:
        rule_id = str(rule.get("rule_id") or "")
        if not rule_id or rule_id in active_runs:
            continue
        started_at = datetime.now(UTC).isoformat()
        try:
            run_monitor_rule_via_api(rule_id)
        except WorkflowAPIError as exc:
            errors.append(f"{rule.get('name', rule_id)}：{exc}")
            continue
        active_runs[rule_id] = {
            "started_at": started_at,
            "rule_name": str(rule.get("name") or "未命名规则"),
        }
        started_count += 1
    st.session_state.monitor_active_runs = active_runs
    return started_count, errors


def render_monitor_management_page() -> None:
    st.markdown(
        """
        <div class="chat-header">
          <div class="chat-title">信息监控 <span class="status-dot"></span></div>
          <div class="muted">Monitor Agent · Web Research · Scheduler</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("持续跟踪指定公司、招聘、新闻、GitHub 项目和技术博客；首次运行只建立基线。")

    if st.session_state.monitor_notice:
        st.success(st.session_state.monitor_notice)
        st.session_state.monitor_notice = ""
    if st.session_state.monitor_error:
        st.error(st.session_state.monitor_error)
        st.session_state.monitor_error = ""

    try:
        status = get_automation_status_via_api()
        rules = list_monitor_rules_via_api()
    except WorkflowAPIError as exc:
        st.error(str(exc))
        return

    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("监控规则", len(rules))
    metric_b.metric("已启用", len([rule for rule in rules if rule.get("enabled")]))
    metric_c.metric("后台调度", "运行中" if status.get("running") else "未启动")
    metric_d.metric("GitHub API", "已认证" if status.get("github_token_configured") else "匿名")

    enabled_rules = [rule for rule in rules if rule.get("enabled")]
    active_runs = st.session_state.get("monitor_active_runs") or {}
    hot_ai_preset_exists = any(
        rule.get("target_type") == "github"
        and rule.get("target") == "热门 AI 项目"
        for rule in rules
    )
    run_col, preset_col = st.columns([0.62, 0.38])
    with run_col:
        run_label = "立即运行一次" if len(enabled_rules) <= 1 else "立即运行全部监控"
        if st.button(
            run_label,
            type="primary",
            use_container_width=True,
            disabled=not enabled_rules or all(
                str(rule.get("rule_id")) in active_runs for rule in enabled_rules
            ),
            key="monitor_run_all_now",
        ):
            started_count, errors = _start_monitor_runs(enabled_rules)
            if started_count:
                st.session_state.monitor_notice = f"已启动 {started_count} 条监控任务，页面会自动显示结果。"
            if errors:
                st.session_state.monitor_error = "；".join(errors)
            st.rerun()
    with preset_col:
        if st.button(
            "添加热门 AI 项目监控",
            use_container_width=True,
            disabled=hot_ai_preset_exists,
            key="monitor_add_hot_ai_preset",
        ):
            try:
                create_monitor_rule_via_api(
                    {
                        "name": "热门 AI 项目",
                        "target_type": "github",
                        "target": "热门 AI 项目",
                        "query": "LLM Agent RAG MCP 热门项目",
                        "interval_minutes": 360,
                        "enabled": True,
                    }
                )
                st.session_state.monitor_notice = "热门 AI 项目监控已创建，首次检查将建立基线。"
            except WorkflowAPIError as exc:
                st.session_state.monitor_error = str(exc)
            st.rerun()
    if not status.get("configured_enabled"):
        st.info("自动调度默认关闭。可在 .env 中设置 AUTOMATION_SCHEDULER_ENABLED=true 后重启 API；仍可手动立即检查。")

    with st.expander("新建监控规则", expanded=not rules):
        with st.form("create_monitor_rule_form", clear_on_submit=True):
            name = st.text_input("规则名称", placeholder="例如：Vercel 招聘变化")
            target_label = st.selectbox("监控类型", list(MONITOR_TARGET_LABELS))
            target = st.text_input("监控目标", placeholder="公司名、仓库名或博客名称")
            query = st.text_input("检索要求", placeholder="例如：Vercel 中国区 AI 工程师招聘 最新")
            interval_minutes = st.number_input(
                "检查间隔（分钟）",
                min_value=15,
                max_value=10080,
                value=360,
                step=15,
            )
            submitted = st.form_submit_button("创建规则", use_container_width=True)
        if submitted:
            if not all(value.strip() for value in (name, target, query)):
                st.session_state.monitor_error = "规则名称、监控目标和检索要求不能为空。"
            else:
                try:
                    create_monitor_rule_via_api(
                        {
                            "name": name.strip(),
                            "target_type": MONITOR_TARGET_LABELS[target_label],
                            "target": target.strip(),
                            "query": query.strip(),
                            "interval_minutes": int(interval_minutes),
                            "enabled": True,
                        }
                    )
                    st.session_state.monitor_notice = "监控规则已创建，首次检查将建立对比基线。"
                except WorkflowAPIError as exc:
                    st.session_state.monitor_error = str(exc)
            st.rerun()

    st.markdown("### 监控规则")
    if not rules:
        st.info("还没有监控规则。")
        return
    for rule in rules:
        rule_id = str(rule["rule_id"])
        active_run = (st.session_state.get("monitor_active_runs") or {}).get(rule_id)
        with st.container(border=True):
            detail_col, action_col = st.columns([0.72, 0.28], vertical_alignment="center")
            with detail_col:
                state_label = "已启用" if rule.get("enabled") else "已停用"
                st.markdown(f"**{rule.get('name', '未命名规则')}** · {state_label}")
                st.markdown(rule.get("query", ""))
                last_run = rule.get("last_run_at") or "尚未运行"
                st.caption(
                    f"{rule.get('target_type')} · {rule.get('target')} · "
                    f"每 {rule.get('interval_minutes')} 分钟 · 上次运行 {last_run}"
                )
            with action_col:
                if st.button(
                    "运行中..." if active_run else "立即运行一次",
                    key=f"monitor_run_{rule_id}",
                    use_container_width=True,
                    disabled=bool(active_run),
                ):
                    started_count, errors = _start_monitor_runs([rule])
                    if started_count:
                        st.session_state.monitor_notice = "监控任务已启动，页面会自动显示本次结果。"
                    if errors:
                        st.session_state.monitor_error = "；".join(errors)
                    st.rerun()
                toggle_label = "停用" if rule.get("enabled") else "启用"
                if st.button(
                    toggle_label,
                    key=f"monitor_toggle_{rule_id}",
                    use_container_width=True,
                ):
                    try:
                        update_monitor_rule_via_api(
                            rule_id,
                            {"enabled": not bool(rule.get("enabled"))},
                        )
                    except WorkflowAPIError as exc:
                        st.session_state.monitor_error = str(exc)
                    st.rerun()
                with st.popover("管理", use_container_width=True):
                    st.caption("删除后会同时删除该规则的历史快照。")
                    if st.button(
                        "删除规则",
                        key=f"monitor_delete_{rule_id}",
                        use_container_width=True,
                    ):
                        try:
                            delete_monitor_rule_via_api(rule_id)
                            st.session_state.monitor_notice = "监控规则已删除。"
                        except WorkflowAPIError as exc:
                            st.session_state.monitor_error = str(exc)
                        st.rerun()
            if active_run:
                render_monitor_active_run(rule_id, str(active_run.get("started_at") or ""))
            else:
                try:
                    latest_result = get_monitor_latest_result_via_api(rule_id)
                except WorkflowAPIError as exc:
                    st.error(str(exc))
                else:
                    render_monitor_latest_result(
                        latest_result,
                        expanded=rule_id
                        in set(
                            st.session_state.get("monitor_expanded_result_rule_ids")
                            or set()
                        ),
                    )


def render_monitor_notification_panel() -> None:
    st.markdown("### 通知中心")
    unread_only = st.toggle("只看未读", value=False, key="monitor_unread_only")
    try:
        notifications = list_notifications_via_api(
            unread_only=unread_only,
            limit=50,
            kind="monitor",
        )
        unread_count = get_notification_unread_count_via_api(kind="monitor")
    except WorkflowAPIError as exc:
        st.error(str(exc))
        return
    title_col, action_col = st.columns([0.55, 0.45], vertical_alignment="center")
    title_col.caption(f"{unread_count} 条未读通知")
    with action_col:
        if st.button(
            "全部已读",
            use_container_width=True,
            disabled=unread_count == 0,
            key="monitor_mark_all_read",
        ):
            try:
                mark_all_notifications_read_via_api(kind="monitor")
            except WorkflowAPIError as exc:
                st.error(str(exc))
            st.rerun()
    if not notifications:
        st.info("暂无通知。建立基线不会产生提醒，发现新增或显著变化时才会通知。")
    for notification in notifications:
        notification_id = str(notification["notification_id"])
        unread_prefix = "未读 · " if not notification.get("read") else ""
        with st.container(border=True):
            st.markdown(f"**{unread_prefix}{notification.get('title', '通知')}**")
            if notification.get("content"):
                st.markdown(notification["content"])
            st.caption(
                f"{notification.get('source_agent') or 'system'} · "
                f"{notification.get('created_at', '')}"
            )
            read_label = "标为未读" if notification.get("read") else "阅读完成"
            if st.button(
                read_label,
                key=f"notification_read_{notification_id}",
                use_container_width=True,
            ):
                try:
                    mark_notification_read_via_api(
                        notification_id,
                        read=not bool(notification.get("read")),
                    )
                except WorkflowAPIError as exc:
                    st.error(str(exc))
                st.rerun()


def render_memory_system_page() -> None:
    st.markdown(
        """
        <div class="chat-header">
          <div class="chat-title">记忆系统 <span class="status-dot"></span></div>
          <div class="muted">Memory Agent · retrieve · extract · validate · update</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    type_col, status_col = st.columns(2)
    with type_col:
        memory_type = st.selectbox(
            "记忆类型",
            ["全部", "profile", "preference", "project", "instruction"],
            label_visibility="collapsed",
        )
    with status_col:
        memory_status = st.selectbox(
            "记忆状态",
            ["全部状态", "已启用", "已禁用"],
            label_visibility="collapsed",
        )
    memories = (
        MEMORY_STORE.list_all()
        if memory_type == "全部"
        else MEMORY_STORE.list_by_type(memory_type)
    )
    if memory_status == "已启用":
        memories = [memory for memory in memories if memory.enabled]
    elif memory_status == "已禁用":
        memories = [memory for memory in memories if not memory.enabled]

    if not memories:
        st.info("暂无长期记忆。")
        return

    st.caption(f"共 {len(memories)} 条长期记忆")
    for memory in memories:
        with st.container(border=True):
            top_col, action_col = st.columns([0.82, 0.18], vertical_alignment="center")
            with top_col:
                status_label = "已启用" if memory.enabled else "已禁用"
                st.markdown(
                    f"**{memory.type}** · {status_label} · confidence `{memory.confidence:.2f}`"
                )
                st.markdown(memory.content)
                st.caption(
                    f"使用 {memory.usage_count} 次 · 更新于 {memory.updated_at[:19]}"
                )
            with action_col:
                toggle_label = "禁用" if memory.enabled else "启用"
                if st.button(
                    toggle_label,
                    key=f"toggle_memory_{memory.memory_id}",
                    use_container_width=True,
                ):
                    MEMORY_STORE.set_enabled(memory.memory_id, not memory.enabled)
                    st.rerun()
                if st.button(
                    "删除",
                    key=f"delete_memory_{memory.memory_id}",
                    use_container_width=True,
                ):
                    MEMORY_STORE.delete(memory.memory_id)
                    st.rerun()
            with st.expander("编辑", expanded=False):
                edit_type = st.selectbox(
                    "类型",
                    ["profile", "preference", "project", "instruction"],
                    index=["profile", "preference", "project", "instruction"].index(memory.type),
                    key=f"edit_memory_type_{memory.memory_id}",
                )
                edit_content = st.text_area(
                    "内容",
                    value=memory.content,
                    key=f"edit_memory_content_{memory.memory_id}",
                    height=96,
                )
                edit_confidence = st.slider(
                    "置信度",
                    min_value=0.0,
                    max_value=1.0,
                    value=float(memory.confidence),
                    step=0.01,
                    key=f"edit_memory_confidence_{memory.memory_id}",
                )
                if st.button(
                    "保存修改",
                    key=f"save_memory_{memory.memory_id}",
                    use_container_width=True,
                ):
                    MEMORY_STORE.update(
                        memory.memory_id,
                        memory_type=edit_type,
                        content=edit_content,
                        confidence=edit_confidence,
                    )
                    st.rerun()


def render_skill_management_page() -> None:
    st.markdown(
        """
        <div class="chat-header">
          <div class="chat-title">技能管理 <span class="status-dot"></span></div>
          <div class="muted">Local Skill Registry · load · enable · inject</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_skill_import_section()
    skills = SKILL_REGISTRY.list_skills()
    if not skills:
        st.info("暂无本地 Skills。请在 skills/<skill_name>/SKILL.md 中添加技能。")
        return

    enabled_count = len([skill for skill in skills if skill.enabled])
    st.caption(f"共 {len(skills)} 个本地技能 · 已启用 {enabled_count} 个")
    for skill in skills:
        with st.container(border=True):
            top_col, action_col = st.columns([0.82, 0.18], vertical_alignment="center")
            with top_col:
                status_label = "已启用" if skill.enabled else "已禁用"
                runtime_report = SKILL_RUNTIME_INSPECTOR.inspect(skill)
                runtime_label = {
                    "ready": "运行环境可用",
                    "missing": "缺少本地命令",
                    "no_runtime": "无需本地命令",
                }.get(runtime_report.status, runtime_report.status)
                st.markdown(f"**{skill.name}** · {status_label}")
                st.markdown(skill.description or "暂无描述")
                st.caption(f"Runtime：{runtime_label}")
                st.caption(f"来源：{skill.source_path}")
            with action_col:
                toggle_label = "禁用" if skill.enabled else "启用"
                if st.button(
                    toggle_label,
                    key=f"toggle_skill_{skill.skill_id}",
                    use_container_width=True,
                ):
                    SKILL_REGISTRY.set_enabled(skill.skill_id, not skill.enabled)
                    st.rerun()
                if st.button(
                    "删除",
                    key=f"delete_skill_{skill.skill_id}",
                    use_container_width=True,
                ):
                    try:
                        SKILL_REGISTRY.delete(skill.skill_id)
                        st.success(f"已删除 Skill：{skill.name}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"删除失败：{exc}")
                if runtime_report.install_commands:
                    if st.button(
                        "安装/修复运行时",
                        key=f"quick_install_skill_{skill.skill_id}",
                        use_container_width=True,
                    ):
                        install_result = SKILL_RUNTIME_INSTALLER.install(skill, 0)
                        if install_result.success:
                            st.success("运行时安装命令执行成功。")
                        else:
                            st.error(
                                f"运行时安装命令执行失败，退出码：{install_result.returncode}"
                            )
                        if install_result.stdout:
                            st.code(install_result.stdout, language="text")
                        if install_result.stderr:
                            st.code(install_result.stderr, language="text")
            with st.expander("预览 SKILL.md", expanded=False):
                st.markdown(skill.body or "暂无正文")
            with st.expander("Runtime 检查", expanded=False):
                runtime_report = SKILL_RUNTIME_INSPECTOR.inspect(skill)
                if not runtime_report.commands:
                    st.caption("未识别到需要本地 CLI 的命令。")
                else:
                    for command in runtime_report.commands:
                        availability = "可用" if command.available else "不可用"
                        st.markdown(f"- `{command.name}`：{availability}")
                        for example in command.examples:
                            st.code(example, language="bash")
                if runtime_report.install_commands:
                    st.markdown("安装命令")
                    for index, install_command in enumerate(runtime_report.install_commands):
                        st.code(install_command, language="bash")
                        if st.button(
                            "执行安装命令",
                            key=f"install_skill_{skill.skill_id}_{index}",
                            use_container_width=True,
                        ):
                            install_result = SKILL_RUNTIME_INSTALLER.install(skill, index)
                            if install_result.success:
                                st.success("安装命令执行成功。")
                            else:
                                st.error(
                                    f"安装命令执行失败，退出码：{install_result.returncode}"
                                )
                            if install_result.stdout:
                                st.code(install_result.stdout, language="text")
                            if install_result.stderr:
                                st.code(install_result.stderr, language="text")
                bindings = SKILL_TOOL_BINDING_SERVICE.bindings_for(skill)
                if bindings:
                    st.markdown("Tool Binding")
                    for binding in bindings:
                        availability = "可注册" if binding.available and skill.enabled else "不可注册"
                        st.markdown(
                            f"- `{binding.tool_name}` -> `{binding.command_name}`：{availability}"
                        )


def render_wiki_knowledge_page() -> None:
    current_settings = load_settings()
    gbrain_enabled = is_gbrain_enabled_setting(current_settings)
    gbrain_inbox_dir = get_gbrain_inbox_dir_setting(current_settings)
    wiki_job = sync_wiki_import_job()
    wiki_job_active = wiki_job is not None and wiki_job.state in {"queued", "running"}
    if st.session_state.get("wiki_overview_graph") is None or st.session_state.get("wiki_overview_refresh_needed"):
        refresh_wiki_overview()
    st.markdown(
        """
        <div class="chat-header">
          <div class="chat-title">LLM Wiki 知识库 <span class="status-dot"></span></div>
          <div class="muted">GBrain 原生 MCP · capture · search · graph</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="wiki-hero">
          <div class="wiki-kicker">// LLM WIKI · KNOWLEDGE NETWORK</div>
          <div class="wiki-title">上传原始资料，交给 GBrain 原生索引</div>
          <div class="wiki-desc">
            PMAA 只负责把文件放入 Inbox，并调用 GBrain 原生 capture 写入来源页。
            文本分块、向量化和检索由 GBrain 完成；不会在上传时由 PMAA 自定义生成若干语义 Wiki 节点。
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not gbrain_enabled:
        st.warning("当前未启用 GBrain MCP。请在 .env 中设置 GBRAIN_MCP_ENABLED=true。")

    upload_col, preview_col = st.columns([0.42, 0.58], gap="medium")
    with upload_col:
        with st.container(border=True):
            st.markdown("#### 上传资料")
            st.caption(f"Inbox：`{gbrain_inbox_dir}`")
            uploaded_file = st.file_uploader(
                "上传资料文件",
                type=["pdf", "docx", "md", "txt"],
                key="wiki_file_upload",
            )
            title = st.text_input(
                "Wiki 标题",
                placeholder="默认使用文件名",
                key="wiki_upload_title",
            )
            render_wiki_job_watcher()

            if st.button(
                "准备原生导入",
                use_container_width=True,
                key="wiki_create_preview",
                disabled=wiki_job_active,
            ):
                if uploaded_file is None:
                    st.warning("请先选择一个资料文件。")
                else:
                    job = start_wiki_preview_job(
                        filename=uploaded_file.name,
                        data=uploaded_file.getvalue(),
                        title=title.strip() or None,
                    )
                    st.session_state.wiki_import_job_id = job.job_id
                    st.session_state.wiki_preview = None
                    st.session_state.wiki_import_result = None
                    st.session_state.wiki_delete_result = None
                    st.session_state.wiki_skill_result = None
                    st.session_state.wiki_semantic_result = None
                    st.session_state.wiki_overview_highlights = set()
                    st.session_state.wiki_error = ""
                    st.rerun()

            preview = st.session_state.get("wiki_preview")
            if preview is not None:
                if st.button(
                    "确认写入 GBrain 原生来源库",
                    type="primary",
                    use_container_width=True,
                    key="wiki_confirm_import",
                    disabled=not gbrain_enabled or not preview.import_id or wiki_job_active,
                ):
                    job = start_wiki_commit_job(preview.import_id)
                    st.session_state.wiki_import_job_id = job.job_id
                    st.session_state.wiki_import_result = None
                    st.session_state.wiki_delete_result = None
                    st.session_state.wiki_skill_result = None
                    st.session_state.wiki_semantic_result = None
                    st.session_state.wiki_error = ""
                    st.rerun()

            if st.session_state.get("wiki_error"):
                st.error(st.session_state.wiki_error)
            if st.session_state.get("wiki_import_result") is not None:
                result = st.session_state.wiki_import_result
                st.success(f"已写入 {result.page_count} 个 GBrain 原生来源页。")
                st.code("\n".join(result.written_slugs), language="text")
                if st.button(
                    "按 GBrain 官方 Skill 整理此来源页",
                    use_container_width=True,
                    key="wiki_enrich_source",
                    disabled=wiki_job_active,
                    help=(
                        "用于媒体/文章类来源页：按 GBrain 官方 media-ingest 与 "
                        "article-enrichment Skill 提炼摘要、金句、人物和公司，并写回 GBrain。"
                        "技术文档、面试题、方法论资料通常应使用下面的“建立语义知识模型”。"
                    ),
                ):
                    job = start_gbrain_skill_enrichment_job(result.root_slug)
                    st.session_state.wiki_import_job_id = job.job_id
                    st.session_state.wiki_error = ""
                    st.rerun()
                if st.button(
                    "建立语义知识模型（概念 / 方法 / 项目）",
                    use_container_width=True,
                    key="wiki_semantic_model",
                    disabled=wiki_job_active,
                    help="完整读取 GBrain 原生分块，由 LLM 动态建模；不限制知识页数量。",
                ):
                    job = start_semantic_knowledge_model_job(result.root_slug)
                    st.session_state.wiki_import_job_id = job.job_id
                    st.session_state.wiki_delete_result = None
                    st.session_state.wiki_error = ""
                    st.rerun()
            if st.session_state.get("wiki_skill_result") is not None:
                result = st.session_state.wiki_skill_result
                entity_count = len(result.entity_pages)
                st.success(
                    f"已按 {', '.join(result.skill_names)} 整理来源页；"
                    f"创建或更新 {entity_count} 个官方 Skill 实体页。"
                )
                if result.entity_pages:
                    st.code("\n".join(result.entity_pages), language="text")
            if st.session_state.get("wiki_semantic_result") is not None:
                result = st.session_state.wiki_semantic_result
                st.success(
                    f"语义知识建模完成：读取 {result.chunk_count} 个 GBrain 原生分块，"
                    f"写入 {len(result.pages)} 个知识页、{result.relation_count} 条知识关系。"
                )
                if result.pages:
                    st.code("\n".join(result.pages), language="text")
            if st.session_state.get("wiki_delete_result") is not None:
                result = st.session_state.wiki_delete_result
                st.success(
                    f"已删除来源页及相关知识：{result.source_slug}；"
                    f"删除 {len(result.deleted_slugs)} 个页面、{result.deleted_edges} 条关系。"
                )
                if result.deleted_slugs:
                    st.code("\n".join(result.deleted_slugs), language="text")

            # The page may be refreshed or reopened after a successful import.
            # Keep semantic modelling available for all persisted source pages,
            # not only the source that happens to be in this Streamlit session.
            source_nodes = [
                node
                for node in (st.session_state.get("wiki_overview_graph").nodes if st.session_state.get("wiki_overview_graph") else [])
                if node.node_id.startswith("sources/")
            ]
            if source_nodes:
                source_by_slug = {node.node_id: node.label for node in source_nodes}
                selected_source = st.selectbox(
                    "选择已入库来源页进行语义建模",
                    options=list(source_by_slug),
                    format_func=lambda slug: f"{source_by_slug[slug]} · {slug}",
                    key="wiki_existing_source_for_semantic_model",
                )
                if st.button(
                    "对所选来源建立语义知识模型",
                    use_container_width=True,
                    key="wiki_semantic_model_existing_source",
                    disabled=wiki_job_active,
                    help="完整读取该来源的 GBrain 原生分块，不限制知识页数量。",
                ):
                    job = start_semantic_knowledge_model_job(selected_source)
                    st.session_state.wiki_import_job_id = job.job_id
                    st.session_state.wiki_delete_result = None
                    st.session_state.wiki_error = ""
                    st.rerun()
                confirm_delete_source = st.checkbox(
                    "确认删除所选来源页及由它建立的相关知识",
                    key="wiki_confirm_delete_source",
                    disabled=wiki_job_active,
                )
                if st.button(
                    "删除所选来源页及相关知识",
                    use_container_width=True,
                    key="wiki_delete_existing_source",
                    disabled=wiki_job_active or not confirm_delete_source,
                    help="删除会调用 GBrain 的级联删除工具，完成后刷新知识库全景。",
                ):
                    job = start_wiki_delete_source_job(selected_source)
                    st.session_state.wiki_import_job_id = job.job_id
                    st.session_state.wiki_delete_result = None
                    st.session_state.wiki_error = ""
                    st.rerun()

    with preview_col:
        preview = st.session_state.get("wiki_preview")
        overview = st.session_state.get("wiki_overview_graph")
        display_graph = overlay_wiki_graph(overview, preview.graph if preview else None)
        highlighted = set(st.session_state.get("wiki_overview_highlights", set()))
        if preview:
            highlighted.update(page.slug for page in preview.pages)
        stat_a, stat_b, stat_c = st.columns(3)
        with stat_a:
            st.markdown(
                f'<div class="wiki-stat-card"><div class="wiki-stat-value">{len(display_graph.nodes)}</div><div class="wiki-stat-label">已入库页面</div></div>',
                unsafe_allow_html=True,
            )
        with stat_b:
            st.markdown(
                f'<div class="wiki-stat-card"><div class="wiki-stat-value">{len(display_graph.nodes)}</div><div class="wiki-stat-label">知识库节点</div></div>',
                unsafe_allow_html=True,
            )
        with stat_c:
            st.markdown(
                f'<div class="wiki-stat-card"><div class="wiki-stat-value">{len(display_graph.edges)}</div><div class="wiki-stat-label">知识库关系</div></div>',
                unsafe_allow_html=True,
            )
        st.markdown("#### 知识库全景")
        st.caption("这是已入库知识的常驻全景；红色标记仅表示本次导入涉及的原始来源页。")
        if st.button("刷新知识库全景", key="wiki_overview_refresh", use_container_width=True):
            refresh_wiki_overview()
            st.rerun()
        render_wiki_graph(display_graph, highlighted_node_ids=highlighted)
        if preview:
            st.info(f"本次原生导入：{preview.summary}" if preview.summary else "本次原生来源页将写入知识库。")
            st.caption(f"Import ID：`{preview.import_id}` · Root slug：`{preview.root_slug}`")
            with st.expander("本次写入说明", expanded=False):
                st.caption("本次只写入完整原始来源页，并由 GBrain 原生分块、向量化和建立检索索引；不会生成 PMAA 自定义 Wiki 节点。")

    st.markdown("#### 按页面聚焦查看（可选）")
    st.caption("上方始终显示知识库全景；这里仅用于从某个页面向外展开局部关系。")
    root_slug = st.text_input(
        "Root slug",
        value=(st.session_state.get("wiki_preview").root_slug if st.session_state.get("wiki_preview") else ""),
        placeholder="例如 concepts/rag",
        key="wiki_visualize_root_slug",
    )
    if st.button("调用 wiki_visualize", use_container_width=True, key="wiki_visualize_button"):
        if not root_slug.strip():
            st.warning("请输入 root_slug。")
        else:
            try:
                service = create_gbrain_wiki_service()
                graph = service.visualize(root_slug.strip())
                st.session_state.wiki_visualize_graph = graph
                st.session_state.wiki_error = ""
            except Exception as exc:
                st.session_state.wiki_error = str(exc)
    visualize_graph = st.session_state.get("wiki_visualize_graph")
    if visualize_graph is not None:
        render_wiki_graph(visualize_graph)


def render_skill_import_section() -> None:
    with st.expander("导入外部 Skill 包", expanded=False):
        st.caption("支持 SKILL.md、zip、GitHub 仓库 URL、npx skills add 命令。导入后默认启用，可手动禁用。")
        md_file = st.file_uploader(
            "上传单个 SKILL.md",
            type=["md"],
            key="skill_md_upload",
        )
        if md_file is not None:
            if st.button("导入 SKILL.md", key="import_skill_md", use_container_width=True):
                content = md_file.getvalue().decode("utf-8")
                render_skill_import_result(SKILL_REGISTRY.import_skill_markdown(content))

        zip_file = st.file_uploader(
            "上传 Skills zip（会保留 SKILL.md 同目录下的附属文件）",
            type=["zip"],
            key="skill_zip_upload",
        )
        if zip_file is not None:
            if st.button("导入 zip", key="import_skill_zip", use_container_width=True):
                result = SKILL_REGISTRY.import_skill_zip(zip_file.getvalue())
                render_skill_import_result(result)

        source = st.text_input(
            "从 URL / npx 命令导入",
            placeholder="npx skills add https://github.com/vercel-labs/agent-browser --skill agent-browser",
            key="skill_source_import",
        )
        source_skill_name = st.text_input(
            "Skill 名称（GitHub 仓库 URL 需要填写；npx 命令会自动解析 --skill）",
            placeholder="agent-browser",
            key="skill_source_name",
        )
        if st.button("从来源导入", key="import_skill_source", use_container_width=True):
            if not source.strip():
                st.warning("请输入 SKILL.md URL、zip URL、GitHub 仓库 URL 或 npx skills add 命令。")
            else:
                try:
                    result = SKILL_REGISTRY.import_skill_source(
                        source.strip(),
                        skill_name=source_skill_name.strip(),
                    )
                    render_skill_import_result(result)
                except Exception as exc:
                    st.error(f"导入失败：{exc}")


def render_skill_import_result(result: SkillImportResult) -> None:
    if result.imported:
        names = "、".join(item.name for item in result.imported)
        st.success(f"已导入并启用 {result.imported_count} 个：{names}。")
    if result.skipped:
        names = "、".join(item.name for item in result.skipped)
        st.info(f"已跳过 {result.skipped_count} 个已存在技能：{names}")
    if result.failed:
        messages = "；".join(item.message for item in result.failed)
        st.error(f"导入失败 {result.failed_count} 个：{messages}")


def get_current_messages() -> list:
    task_id = st.session_state.get("current_task_id")
    current_record = HISTORY_STORE.get(task_id) if task_id else None
    return getattr(current_record, "messages", []) if current_record else []


def get_current_input() -> str:
    input_state_key = f"task_input_{st.session_state.task_input_key}"
    return st.session_state.get(input_state_key, st.session_state.task_input)


def set_input_value(value: str) -> None:
    st.session_state.task_input = value
    st.session_state.task_input_key += 1


def render_assistant_message_native(message) -> None:
    avatar_col, content_col = st.columns([0.055, 0.945], gap="small")
    with avatar_col:
        st.markdown('<div class="avatar assistant">A</div>', unsafe_allow_html=True)
    with content_col:
        if getattr(message, "message_type", "normal") == "error":
            st.error(f"任务执行失败：{message.content}")
            return
        if message.view is not None:
            with st.expander("思考过程 / Agent 执行过程", expanded=False):
                policy_card = build_policy_card_markdown(message.view)
                if policy_card:
                    with st.container(border=True):
                        st.markdown(policy_card)
                st.code(build_thought_text(message.view), language="text")
        with st.container(border=True):
            if message_has_pending_confirmation(message):
                render_answer_or_confirmation(message.view)
            else:
                st.markdown(normalize_markdown_content(message.content))


def is_draft_record(record) -> bool:
    return record.view.get("status") == "draft"


def create_new_chat() -> None:
    record = HISTORY_STORE.create_draft()
    st.session_state.current_task_id = record.task_id
    set_input_value("")
    st.session_state.task_view = None
    st.session_state.last_task = record.title
    st.session_state.task_error = ""


def delete_history_record(task_id: str) -> None:
    is_current = st.session_state.get("current_task_id") == task_id
    HISTORY_STORE.delete(task_id)
    if is_current:
        create_new_chat()


def rename_history_record(task_id: str, title: str) -> None:
    record = HISTORY_STORE.rename(task_id, title)
    if st.session_state.get("current_task_id") == task_id:
        st.session_state.last_task = record.title


def load_history_record(record) -> None:
    st.session_state.current_task_id = record.task_id
    set_input_value(record.user_input)
    st.session_state.task_view = None if is_draft_record(record) else record.view
    st.session_state.last_task = record.title
    st.session_state.task_error = ""


def ensure_editable_draft(user_input: str) -> str:
    task_id = st.session_state.get("current_task_id")
    current_record = HISTORY_STORE.get(task_id) if task_id else None
    if current_record is None:
        current_record = HISTORY_STORE.create_draft(user_input)
        st.session_state.current_task_id = current_record.task_id
        st.session_state.task_view = None
    if not is_draft_record(current_record):
        return current_record.task_id
    updated_record = HISTORY_STORE.update_draft(current_record.task_id, user_input)
    st.session_state.last_task = updated_record.title
    return updated_record.task_id


def sync_current_draft() -> None:
    task_id = st.session_state.get("current_task_id")
    current_record = HISTORY_STORE.get(task_id) if task_id else None
    if current_record is not None and is_draft_record(current_record):
        updated_record = HISTORY_STORE.update_draft(
            current_record.task_id,
            get_current_input(),
        )
        st.session_state.last_task = updated_record.title


def run_current_task() -> None:
    input_state_key = f"task_input_{st.session_state.task_input_key}"
    task = (
        st.session_state.pending_task_input.strip()
        or st.session_state.get(input_state_key, "").strip()
        or st.session_state.task_input.strip()
    )
    if not task:
        st.warning("请输入任务内容。")
        return
    if st.session_state.stream_request is not None:
        return
    st.session_state.task_error = ""
    st.session_state.running_task = task
    st.session_state.last_task = task[:32]
    task_id = ensure_editable_draft(task)
    conversation_context = build_conversation_context(get_current_messages())
    try:
        job = submit_multi_agent_job_via_api(
            task,
            conversation_context,
            kind="chat",
            label=task[:100],
            metadata={"history_task_id": task_id},
        )
    except WorkflowAPIError as exc:
        st.session_state.task_error = str(exc)
        st.session_state.running_task = ""
        return
    st.session_state.pending_task_input = ""
    st.session_state.task_input = ""
    st.session_state.task_input_key += 1
    st.session_state.task_view = build_live_view([])
    st.session_state.stream_request = {
        "task": task,
        "task_id": task_id,
        "conversation_context": conversation_context,
        "job_id": str(job["job_id"]),
    }


@st.fragment(run_every="2s")
def render_chat_background_job(stream_request: dict) -> None:
    try:
        job = get_background_job_via_api(str(stream_request["job_id"]))
    except WorkflowAPIError as exc:
        st.error(str(exc))
        return
    progress_events = (job.get("progress") or {}).get("events") or []
    live_events = [
        {
            "agent": event.get("agent", ""),
            "label": AGENT_LABELS.get(
                event.get("agent", ""),
                str(event.get("agent", "Agent")).title(),
            ),
            "event_type": event.get("event_type", ""),
            "output": event.get("output", {}),
            "timestamp": event.get("timestamp", ""),
        }
        for event in progress_events
        if isinstance(event, dict)
    ]
    live_view = build_live_view(live_events)
    with st.expander("思考过程 / Agent 执行过程", expanded=True):
        with st.container(height=360, border=False):
            policy_card = build_policy_card_markdown(live_view)
            if policy_card:
                with st.container(border=True):
                    st.markdown(policy_card)
            st.code(
                build_thought_text(live_view)
                if live_events
                else "后台任务已提交，等待 Agent 开始执行...",
                language="text",
            )
    status = str(job.get("status") or "")
    if status in {"pending", "running"}:
        with st.container(border=True):
            st.markdown("Agent 正在后台执行。你可以切换到其他功能页面。")
        return
    if status == "failed":
        error_message = str(job.get("error") or "未知错误")
        HISTORY_STORE.save_error(
            task_id=stream_request["task_id"],
            user_input=stream_request["task"],
            error_message=error_message,
        )
        st.session_state.task_error = error_message
        st.session_state.stream_request = None
        st.session_state.running_task = ""
        st.rerun(scope="app")
        return
    try:
        workflow_result = WorkflowResult.model_validate(job.get("result") or {})
        final_view = build_task_view(workflow_result)
        HISTORY_STORE.save_result(
            workflow_result,
            final_view,
            task_id=stream_request["task_id"],
        )
        if st.session_state.current_task_id == stream_request["task_id"]:
            st.session_state.task_view = final_view
        st.session_state.task_error = ""
        st.session_state.stream_request = None
        st.session_state.running_task = ""
        st.rerun(scope="app")
        return
    except Exception as exc:
        error_message = str(exc)
        HISTORY_STORE.save_error(
            task_id=stream_request["task_id"],
            user_input=stream_request["task"],
            error_message=error_message,
        )
        st.session_state.task_error = error_message
        st.session_state.stream_request = None
        st.session_state.running_task = ""
        st.rerun(scope="app")
        return


is_running = st.session_state.stream_request is not None

if not is_running:
    sync_current_draft()

view = st.session_state.task_view

st.markdown(
    """
    <div class="topbar">
      <div class="top-left"><span class="mode-pill">学习模式</span></div>
      <div class="top-center"><span class="brand-dot">P</span><span class="brand">Personal Multi-Agent Assistant</span><span class="workspace-link">工作空间</span></div>
      <div class="top-right"><span class="status-dot"></span><span class="muted">System Online</span></div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.active_page == "wiki":
    left, center = st.columns([0.18, 0.82], gap="small")
    right = None
else:
    left, center, right = st.columns([0.18, 0.43, 0.39], gap="small")

with left:
    with st.container(border=True):
        with st.container(key="nav_panel"):
            if st.button("对话  Chat", key="nav_chat", use_container_width=True):
                st.session_state.active_page = "chat"
                st.rerun()
            if st.button("技能管理  Agent Skills", key="nav_skills", use_container_width=True):
                st.session_state.active_page = "skills"
                st.rerun()
            if st.button("记忆系统  Memory System", key="nav_memory", use_container_width=True):
                st.session_state.active_page = "memory"
                st.rerun()
            render_email_nav_button()
            render_notification_nav_button(
                kind="daily_brief",
                label="每日简报  Daily Brief",
                page="brief",
                button_key="nav_daily_brief",
            )
            render_notification_nav_button(
                kind="monitor",
                label="信息监控  Monitor",
                page="monitor",
                button_key="nav_monitor",
            )
            if st.button("LLM Wiki 知识库", key="nav_wiki", use_container_width=True):
                st.session_state.active_page = "wiki"
                st.rerun()
        st.markdown('<div class="section-label">NEW CHAT</div>', unsafe_allow_html=True)
        if st.button("新建空对话", use_container_width=True, disabled=is_running):
            create_new_chat()
            st.rerun()
        selected_example = st.selectbox("示例任务", EXAMPLES, label_visibility="collapsed")
        if st.button("填入示例", use_container_width=True):
            ensure_editable_draft(selected_example)
            set_input_value(selected_example)
            st.session_state.task_view = None
            st.rerun()

        st.markdown('<div class="section-label">RECENT</div>', unsafe_allow_html=True)
        recent_records = HISTORY_STORE.list_recent(limit=100)
        if not recent_records:
            st.caption("暂无历史任务")
        with st.container(key="recent_list"):
            for record in recent_records:
                row_key = f"recent_row_{record.task_id.replace('-', '_')}"
                with st.container(key=row_key):
                    title_col, action_col = st.columns(
                        [0.86, 0.14],
                        gap="small",
                        vertical_alignment="center",
                    )
                    title = f"置顶 · {record.title}" if record.pinned else record.title
                    with title_col:
                        if st.button(
                            title,
                            key=f"history_{record.task_id}",
                            use_container_width=True,
                        ):
                            load_history_record(record)
                            st.rerun()
                    with action_col:
                        with st.popover(
                            "⋯",
                            key=f"actions_{record.task_id}",
                            use_container_width=True,
                        ):
                            pin_label = "取消置顶" if record.pinned else "置顶"
                            if st.button(
                                pin_label,
                                key=f"pin_{record.task_id}",
                                use_container_width=True,
                                disabled=is_running,
                            ):
                                HISTORY_STORE.set_pinned(record.task_id, not record.pinned)
                                st.rerun()
                            new_title = st.text_input(
                                "重命名",
                                value=record.title,
                                key=f"rename_text_{record.task_id}",
                            )
                            if st.button(
                                "重命名",
                                key=f"rename_{record.task_id}",
                                use_container_width=True,
                                disabled=is_running,
                            ):
                                rename_history_record(record.task_id, new_title)
                                st.rerun()
                            if st.button(
                                "删除",
                                key=f"delete_{record.task_id}",
                                use_container_width=True,
                                disabled=is_running,
                            ):
                                delete_history_record(record.task_id)
                                st.rerun()

        if recent_records:
            st.markdown('<div class="section-label">EXPORT</div>', unsafe_allow_html=True)
            record_by_label = {
                f"{record.title} · {record.created_at[:10]}": record
                for record in recent_records
            }
            selected_labels = st.multiselect(
                "选择要导出的对话",
                options=list(record_by_label.keys()),
                label_visibility="collapsed",
                placeholder="选择要导出的对话",
            )
            selected_records = [record_by_label[label] for label in selected_labels]
            st.download_button(
                "批量导出 Markdown",
                data=build_bulk_markdown_export(selected_records) if selected_records else "",
                file_name=build_bulk_export_filename(),
                mime="text/markdown",
                use_container_width=True,
                disabled=not selected_records,
            )

if st.session_state.active_page == "skills":
    with center:
        with st.container(border=True):
            render_skill_management_page()
    with right:
        with st.container(border=True):
            st.markdown("### Skill Trace")
            skills = SKILL_REGISTRY.list_skills()
            st.metric("Skills", len(skills))
            st.metric("Enabled", len([skill for skill in skills if skill.enabled]))
            st.caption("当前会把启用 Skill 的 name / description 作为能力目录交给 LLM 判断。")
            matched_skills = SKILL_REGISTRY.list_enabled_skills()
            st.json(
                [
                    {
                        "id": skill.skill_id,
                        "name": skill.name,
                        "description": skill.description,
                        "tool_name": f"skill:{skill.skill_id}",
                        "enabled": skill.enabled,
                    }
                    for skill in matched_skills
                ]
            )
    st.stop()

if st.session_state.active_page == "memory":
    with center:
        with st.container(border=True):
            render_memory_system_page()
    with right:
        with st.container(border=True):
            memories = MEMORY_STORE.list_all()
            st.markdown("### Memory Trace")
            st.metric("Memories", len(memories))
            st.metric("Enabled", len([memory for memory in memories if memory.enabled]))
            st.metric("Disabled", len([memory for memory in memories if not memory.enabled]))
            type_counts = {}
            for memory in memories:
                type_counts[memory.type] = type_counts.get(memory.type, 0) + 1
            st.json(type_counts)
    st.stop()

if st.session_state.active_page == "email":
    with center:
        with st.container(border=True):
            render_email_assistant_page()
    with right:
        with st.container(border=True):
            render_email_trace_panel()
    st.stop()

if st.session_state.active_page == "brief":
    with center:
        with st.container(border=True):
            render_daily_brief_page()
    with right:
        with st.container(border=True):
            render_daily_brief_data_panel()
    st.stop()

if st.session_state.active_page == "monitor":
    with center:
        with st.container(border=True):
            render_monitor_management_page()
    with right:
        with st.container(border=True):
            render_monitor_notification_panel()
    st.stop()

if st.session_state.active_page == "wiki":
    with center:
        with st.container(border=True):
            render_wiki_knowledge_page()
    st.stop()

with center:
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="chat-header">
              <div class="chat-title">{escape(st.session_state.last_task)} <span class="status-dot"></span></div>
              <div class="muted">StateGraph · Trace · Settings</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="assistant-row">
              <div class="avatar assistant">A</div>
              <div class="message-card">你好，我是 PMAA 多 Agent 可视化助手。输入问题后，我会展示答案和每一步执行状态。</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        messages = get_current_messages()
        for message in messages:
            if message.role == "user":
                st.markdown(
                    render_user_message(message.content),
                    unsafe_allow_html=True,
                )
            else:
                render_assistant_message_native(message)
                continue
                st.markdown('<div class="assistant-row">', unsafe_allow_html=True)
                st.markdown('<div class="avatar assistant">A</div>', unsafe_allow_html=True)
                if getattr(message, "message_type", "normal") == "error":
                    st.markdown(
                        f'<div class="error-box">任务执行失败：{escape(message.content)}</div></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown('<div class="answer-box">', unsafe_allow_html=True)
                    st.markdown(message.content)
                    st.markdown("</div></div>", unsafe_allow_html=True)

        if is_running and st.session_state.stream_request is not None:
            current_stream_request = st.session_state.stream_request
            st.markdown(
                render_user_message(current_stream_request["task"]),
                unsafe_allow_html=True,
            )
            avatar_col, content_col = st.columns([0.055, 0.945], gap="small")
            with avatar_col:
                st.markdown(
                    '<div class="avatar assistant">A</div>',
                    unsafe_allow_html=True,
                )
            with content_col:
                with st.container(key="chat_job_progress"):
                    render_chat_background_job(current_stream_request)

        if not is_running and not messages and get_current_input().strip():
            st.markdown(
                render_user_message(get_current_input()),
                unsafe_allow_html=True,
            )

        if is_running:
            st.info(f"Agent 正在执行任务：{st.session_state.running_task}")
        elif st.session_state.task_error:
            st.error(f"任务执行失败：{st.session_state.task_error}")

        if False:
            st.markdown(
                f'<pre class="readonly-box thought-box">{escape(build_thought_text(view))}</pre>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="field-title">运行结果</div>', unsafe_allow_html=True)
        if is_running:
            st.markdown('<div class="readonly-box">任务运行中，完成后会自动显示结果。</div>', unsafe_allow_html=True)
        elif view is not None and not messages:
            st.markdown('<div class="answer-box">', unsafe_allow_html=True)
            render_answer_or_confirmation(view)
            st.markdown("</div>", unsafe_allow_html=True)
        elif messages:
            st.markdown('<div class="readonly-box">上方已显示当前对话的全部消息。</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="readonly-box">运行后这里会显示最终回答。</div>', unsafe_allow_html=True)

        input_state_key = f"task_input_{st.session_state.task_input_key}"
        st.text_area(
            "输入消息",
            key=input_state_key,
            value=st.session_state.task_input,
            height=92,
            label_visibility="collapsed",
        )
        st.button(
            "发送 / 运行工作流",
            type="primary",
            use_container_width=True,
            on_click=run_current_task,
            key="send_task",
            disabled=is_running,
        )
        if st.session_state.task_error and not is_running:
            if st.button("重试当前任务", key="retry_current_task", use_container_width=True):
                run_current_task()
                st.rerun()

with right:
    with st.container(border=True):
        token_hint = "0 tokens" if view is None else f"{len(str(view)):,} chars"
        st.markdown(
            f"""
            <div class="raw-header">
              <div class="raw-title">Raw Context <span class="token-pill">{token_hint}</span></div>
              <div class="muted">RAG · Trace</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<span class="raw-label">CONTEXT</span>', unsafe_allow_html=True)
        st.text_area(
            "Raw Context",
            value=build_raw_context(view, get_current_input()),
            height=520,
            disabled=True,
            label_visibility="collapsed",
        )

        if view is not None:
            st.markdown('<span class="raw-label">SOURCES</span>', unsafe_allow_html=True)
            for index, source in enumerate(view["sources"], start=1):
                st.markdown(f"[S{index}] [{source['title']}]({source['url']})")
