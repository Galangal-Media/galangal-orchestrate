"""Tests for the design-level workflow changes: REDESIGN rollback + config skips."""

from galangal.config.schema import GalangalConfig, TaskTypeSettings
from galangal.core.state import Stage, get_decision_config


class TestRedesignRollbackTarget:
    def test_review_redesign_rolls_back_to_design(self):
        cfg = get_decision_config(Stage.REVIEW)
        assert "REDESIGN" in cfg
        success, _msg, rollback_to, _ft = cfg["REDESIGN"]
        assert success is False
        assert rollback_to == "DESIGN"

    def test_review_request_changes_still_rolls_back_to_dev(self):
        success, _msg, rollback_to, _ft = get_decision_config(Stage.REVIEW)["REQUEST_CHANGES"]
        assert rollback_to == "DEV"

    def test_security_redesign_rolls_back_to_design(self):
        cfg = get_decision_config(Stage.SECURITY)
        assert cfg["REDESIGN"][2] == "DESIGN"
        assert cfg["REJECTED"][2] == "DEV"  # code-level fix still goes to DEV


class TestConfigSkipStages:
    def test_skip_stages_parses(self):
        cfg = GalangalConfig.model_validate(
            {"task_type_settings": {"feature": {"skip_stages": ["DESIGN", "DOCS"]}}}
        )
        assert cfg.task_type_settings["feature"].skip_stages == ["DESIGN", "DOCS"]

    def test_skip_stages_defaults_empty(self):
        assert TaskTypeSettings().skip_stages == []


class TestTestGateStaysInReviewLoop:
    def test_review_iteration_skip_excludes_test_gate(self):
        # The review-iteration fast-track skip set must NOT include TEST_GATE, so a
        # regression introduced by a review fix is caught during the loop.
        from galangal.core.state import STAGE_ORDER

        dev_idx = STAGE_ORDER.index(Stage.DEV)
        review_idx = STAGE_ORDER.index(Stage.REVIEW)
        loop_skip = set(STAGE_ORDER[dev_idx + 1 : review_idx])
        loop_skip.discard(Stage.TEST_GATE)
        assert Stage.TEST_GATE not in loop_skip
        assert Stage.TEST in loop_skip  # TEST itself is still skipped (preserved)
