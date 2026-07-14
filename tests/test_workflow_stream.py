from pmaa.workflow.graph import stream_workflow_events


def test_stream_workflow_events_emits_agent_events_before_completion():
    events = list(stream_workflow_events("hi"))

    assert events[0]["type"] == "workflow_started"
    assert events[-1]["type"] == "workflow_completed"

    agent_events = [event for event in events if event["type"] == "agent_event"]
    assert [event["event"].agent for event in agent_events] == [
        "supervisor",
        "supervisor",
    ]
    assert agent_events[0]["event"].output["execution_mode"] == "direct_answer"
    assert events[-1]["result"].final_result is not None
