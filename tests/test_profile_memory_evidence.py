from user_profile.dynamic_updater import DynamicProfileUpdater


def test_explicit_action_has_provenance():
    result = DynamicProfileUpdater().analyze_message(
        "u1", "我今天坐地铁去上班了", "ACTION_REPORT"
    )
    action = result["action_reports"][0]
    assert action["source"] == "chat_explicit"
    assert action["confidence"] >= 0.8
    assert action["observed_at"]


def test_negated_action_is_not_written_as_completed_behavior():
    result = DynamicProfileUpdater().analyze_message(
        "u1", "我今天没有坐地铁", "ACTION_REPORT"
    )
    assert not any(a["action"] == "坐地铁" for a in result["action_reports"])
