from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from repoevidence import __version__
from repoevidence.assessment import assess_repository
from repoevidence.models import VerificationError, VerificationMetadata, VerificationResult
from repoevidence.operations import OperationEvent, WorkspaceOperationResult
from repoevidence.project_context import GitContext, ProjectContext
from repoevidence.report_manifest import assess_report
from repoevidence.status import ArtifactLifecycle, DomainOutcome, Freshness, OperationState
from repoevidence.user_config import UserSettings
from repoevidence.workspace import WorkspaceCheck, build_workspace_projection


def _fresh_app_inputs(tmp_path: Path):
    root = tmp_path / "service"
    root.mkdir()
    context = ProjectContext(
        project_root=root,
        opened_from=root,
        repository_name="service",
        git=GitContext(
            repository=False,
            top_level=None,
            branch=None,
            commit=None,
            dirty=False,
            status_known=True,
        ),
    )
    projection = build_workspace_projection(
        context,
        assess_repository(root, require_static=False),
        report_assessment=assess_report(root, language="en"),
        language="en",
    )
    return root, context, projection


def test_startup_is_read_only_and_default_focus_is_primary_action(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    root, context, projection = _fresh_app_inputs(tmp_path)
    calls: list[str] = []

    class Controller:
        def invoke(self, action: str) -> None:
            calls.append(action)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
            controller=Controller(),
        ).run_test(size=(80, 24)) as pilot:
            assert pilot.app.query_one("#primary-action").has_focus
            assert "RepoEvidence" in str(pilot.app.query_one("#project-header").render())
            assert "Not inspected" in pilot.app.query_one("#ledger-source").render().plain
            assert calls == []
            assert not (root / ".repoevidence").exists()
            await pilot.press("q")

    asyncio.run(scenario())


def test_header_separates_product_project_snapshot_and_conditional_opened_from(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    root, context, projection = _fresh_app_inputs(tmp_path)
    same_location_context = replace(context, repository_name="RepoEvidence")

    async def scenario() -> None:
        async with RepoEvidenceApp(
            same_location_context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            header = pilot.app.query_one("#project-header").render().plain
            lines = header.splitlines()
            assert lines[0] == "RepoEvidence"
            assert lines[1] != "RepoEvidence"
            assert "Git:" not in header
            assert "Project root:" in header
            assert "Opened from:" not in header

            pilot.app.context = replace(
                pilot.app.context,
                repository_name="service",
            )
            pilot.app._refresh_labels()
            header = pilot.app.query_one("#project-header").render().plain
            lines = header.splitlines()
            assert lines[1] == "service"
            assert "Git:" not in header
            assert "Project root:" in header
            assert "Opened from:" not in header

            pilot.app.context = replace(pilot.app.context, opened_from=tmp_path)
            pilot.app._refresh_labels()
            header = pilot.app.query_one("#project-header").render().plain
            assert "Opened from:" in header
            await pilot.press("q")

    asyncio.run(scenario())


def test_narrow_header_hides_muted_project_root_metadata(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(60, 24)) as pilot:
            header = pilot.app.query_one("#project-header").render().plain
            assert "Project root:" not in header
            assert "Opened from:" not in header
            await pilot.press("q")

    asyncio.run(scenario())


def test_workspace_uses_human_first_layer_labels_without_operation_debug_text(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            source = pilot.app.query_one("#ledger-source").render().plain
            runtime = pilot.app.query_one("#ledger-runtime").render().plain
            comparison = pilot.app.query_one("#ledger-comparison").render().plain
            assert "Not inspected" in source
            assert "idle" not in source.lower()
            assert "[--]" not in source
            assert "MySQL database" in runtime
            assert "Source and database" in comparison
            await pilot.press("q")

    asyncio.run(scenario())


def test_onboarding_copy_is_hidden_once_source_artifact_exists(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    root, context, _ = _fresh_app_inputs(tmp_path)
    from repoevidence.application import scan_repository

    scan_repository(root)
    projection = build_workspace_projection(
        context,
        assess_repository(root, require_static=False),
        report_assessment=assess_report(root, language="en"),
        language="en",
    )

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            assert not pilot.app.query_one("#summary").display
            await pilot.press("q")

    asyncio.run(scenario())


def test_empty_activity_is_collapsed_and_populated_activity_is_visible(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            assert not pilot.app.query_one("#activity").display
            pilot.app._record_activity("Inspect source completed")
            pilot.app._refresh_labels()
            assert pilot.app.query_one("#activity").display
            assert "Inspect source completed" in pilot.app.query_one(
                "#activity-log"
            ).render().plain
            await pilot.press("q")

    asyncio.run(scenario())


def test_footer_keeps_language_and_status_discoverable_without_footer_cheatsheet(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            assert pilot.app.query_one("#footer-status")
            assert pilot.app.query_one("#footer-language").render().plain == "English · en"
            assert pilot.app.query_one("#settings-action")
            assert pilot.app.query_one("#help-action")
            assert pilot.app.query_one("#quit-action")
            assert not pilot.app.query("Footer")
            await pilot.press("q")


def test_default_context_hides_machine_values_and_technical_details_are_collapsed(
    tmp_path: Path,
) -> None:
    from textual.widgets import Collapsible

    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            detail = pilot.app.query_one("#context-detail").render().plain
            technical = pilot.app.query_one("#technical-details", Collapsible)
            assert technical.collapsed
            assert "Source has not been checked" in detail
            assert "Coverage:" in detail
            for raw_value in (
                "valid",
                "fresh",
                "not_available",
                "runtime_failed",
                "artifact_missing",
                "not_applicable",
            ):
                assert raw_value not in detail
            await pilot.press("q")

    asyncio.run(scenario())


def test_technical_details_are_keyboard_accessible_and_keep_machine_values(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            technical = pilot.app.query_one("#technical-details")
            title = technical.query_one("CollapsibleTitle")
            title.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert not technical.collapsed
            technical_detail = technical.query_one("#technical-details-copy").render().plain
            assert "Lifecycle: missing" in technical_detail
            assert "Freshness: not_applicable" in technical_detail
            assert "Operation: idle" in technical_detail
            assert "Outcome: not_available" in technical_detail
            assert "Reason codes: artifact_missing" in technical_detail
            await pilot.press("enter")
            await pilot.pause()
            assert technical.collapsed
            await pilot.press("q")

    asyncio.run(scenario())


def test_report_language_is_rendered_as_report_language_not_explanation(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    report = replace(
        projection.report,
        lifecycle=ArtifactLifecycle.VALID,
        freshness=Freshness.FRESH,
        operation=OperationState.SUCCEEDED,
        observed_at=datetime(2026, 8, 9, 11, 0, tzinfo=timezone.utc),
        provenance_summary=("zh-CN",),
        reason_codes=(),
        available_actions=("view.report", "report.refresh", "report.open"),
    )
    projection = replace(projection, report=report, selected_id="report")

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="zh-CN",
            settings=UserSettings(language="zh-CN"),
        ).run_test(size=(100, 30)) as pilot:
            detail = pilot.app.query_one("#context-detail").render().plain
            assert "报告语言：简体中文 · zh-CN" in detail
            assert "这意味着\n· zh-CN" not in detail
            assert "报告已生成" in detail
            assert "生成时间：2026-08-09 11:00 UTC" in detail
            await pilot.press("q")

    asyncio.run(scenario())


def test_language_switch_relabels_collapsible_without_translating_machine_values(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    report = replace(
        projection.report,
        lifecycle=ArtifactLifecycle.VALID,
        freshness=Freshness.FRESH,
        operation=OperationState.SUCCEEDED,
        observed_at=datetime(2026, 8, 9, 11, 0, tzinfo=timezone.utc),
        provenance_summary=("en",),
        reason_codes=(),
        available_actions=("view.report", "report.open"),
    )
    projection = replace(projection, report=report, selected_id="report")

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            technical = pilot.app.query_one("#technical-details")
            technical.query_one("CollapsibleTitle").focus()
            await pilot.press("enter")
            await pilot.pause()
            assert not technical.collapsed
            assert "Freshness: fresh" in technical.query_one(
                "#technical-details-copy"
            ).render().plain
            pilot.app.set_language("zh-CN")
            await pilot.pause()
            assert technical.title == "技术信息"
            assert not technical.collapsed
            assert "新鲜度：fresh" in technical.query_one(
                "#technical-details-copy"
            ).render().plain
            technical_copy = technical.query_one("#technical-details-copy").render().plain
            assert "操作：succeeded" in technical_copy
            assert "原因代码：" in technical_copy
            detail = pilot.app.query_one("#context-detail").render().plain
            assert "报告语言：English · en" in detail
            await pilot.press("q")

    asyncio.run(scenario())


def test_context_detail_uses_natural_language_for_review_states(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    source = replace(
        projection.source,
        lifecycle=ArtifactLifecycle.VALID,
        freshness=Freshness.UNCERTAIN,
        operation=OperationState.SUCCEEDED,
        outcome=DomainOutcome.SOURCE_ONLY,
        reason_codes=("dirty_worktree_provenance_insufficient",),
        available_actions=("view.source", "source.inspect"),
    )
    runtime = replace(
        projection.runtime,
        lifecycle=ArtifactLifecycle.FAILED,
        freshness=Freshness.NOT_APPLICABLE,
        operation=OperationState.FAILED,
        outcome=DomainOutcome.RUNTIME_FAILED,
        reason_codes=("mysql_connection_failed", "operation_errors"),
        available_actions=("view.runtime", "runtime.verify_mysql", "help.open"),
    )
    comparison = replace(
        projection.comparison,
        lifecycle=ArtifactLifecycle.VALID,
        freshness=Freshness.FRESH,
        operation=OperationState.SUCCEEDED,
        outcome=DomainOutcome.DRIFT_DETECTED,
        reason_codes=(),
        available_actions=("view.finding", "view.comparison", "comparison.reconcile"),
    )
    failed_comparison = replace(
        projection.comparison,
        lifecycle=ArtifactLifecycle.FAILED,
        freshness=Freshness.NOT_APPLICABLE,
        operation=OperationState.FAILED,
        outcome=DomainOutcome.RUNTIME_FAILED,
        reason_codes=("operation_errors",),
        available_actions=("comparison.reconcile", "help.open"),
    )
    stale_report = replace(
        projection.report,
        lifecycle=ArtifactLifecycle.VALID,
        freshness=Freshness.STALE,
        operation=OperationState.SUCCEEDED,
        provenance_summary=("en",),
        reason_codes=("output_hash_mismatch",),
        available_actions=("view.report", "report.refresh", "report.open"),
    )
    cases: tuple[tuple[str, WorkspaceCheck, str], ...] = (
        ("source", source, "cannot confirm this result still matches the current source"),
        ("runtime", runtime, "MySQL verification failed"),
        ("comparison", comparison, "Differences were found"),
        ("comparison", failed_comparison, "Comparison failed"),
        ("report", stale_report, "Report needs refresh"),
    )

    async def scenario() -> None:
        for check_id, check, expected in cases:
            case_projection = replace(
                projection,
                **{check_id: check, "selected_id": check_id},
            )
            async with RepoEvidenceApp(
                context,
                case_projection,
                language="en",
                settings=UserSettings(),
            ).run_test(size=(100, 30)) as pilot:
                detail = pilot.app.query_one("#context-detail").render().plain
                assert expected in detail
                assert "valid" not in detail
                assert "\nfresh\n" not in detail
                assert "not_available" not in detail
                assert "runtime_failed" not in detail
                if check_id == "runtime" and check.lifecycle is ArtifactLifecycle.FAILED:
                    assert "Snapshot:" not in detail
                await pilot.press("q")

    asyncio.run(scenario())


def test_selected_ledger_remains_visible_when_footer_action_is_focused(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    projection = replace(projection, selected_id="runtime")

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            row = pilot.app.query_one("#row-runtime")
            settings = pilot.app.query_one("#settings-action")
            settings.focus()
            await pilot.pause()
            assert settings.has_focus
            assert not pilot.app.query_one("#ledger").has_focus
            assert row.has_class("selected-row")
            assert row.has_class("-highlight")
            assert row.styles.border_left[0] == "tall"
            await pilot.press("q")

    asyncio.run(scenario())


def test_footer_uses_brand_case_and_unambiguous_report_status(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    report = replace(
        projection.report,
        lifecycle=ArtifactLifecycle.VALID,
        freshness=Freshness.FRESH,
        operation=OperationState.SUCCEEDED,
        reason_codes=(),
        provenance_summary=("en",),
        available_actions=("view.report", "report.open"),
    )
    projection = replace(projection, report=report)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            footer = pilot.app.query_one("#footer-status").render().plain
            assert "MySQL" in footer
            assert " mysql " not in footer
            assert "Report ✓" in footer
            assert "+" not in footer
            await pilot.press("q")

    asyncio.run(scenario())

    asyncio.run(scenario())


def test_selected_and_focused_ledger_states_remain_separate(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            ledger = pilot.app.query_one("#ledger")
            ledger.focus()
            await pilot.press("down")
            assert ledger.has_focus
            assert pilot.app.selected_id == "runtime"
            assert pilot.app.query_one("#row-runtime").has_class("-highlight")
            await pilot.press("q")

    asyncio.run(scenario())


def test_projection_selection_drives_initial_detail_context(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    projection = replace(projection, selected_id="runtime")

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            assert pilot.app.selected_id == "runtime"
            assert pilot.app.query_one("#row-runtime").has_class("-highlight")
            detail = pilot.app.query_one("#context-detail").render().plain
            assert "MySQL database" in detail
            await pilot.press("q")

    asyncio.run(scenario())


def test_narrow_mode_keeps_core_status_and_primary_action_visible(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(40, 24)) as pilot:
            assert pilot.app.has_class("narrow")
            assert pilot.app.has_class("very-narrow")
            assert pilot.app.query_one("#primary-action").display
            primary = pilot.app.query_one("#primary-action")
            detail_pane = pilot.app.query_one("#detail-pane")
            assert primary.region.bottom <= detail_pane.region.bottom
            assert primary.render().plain
            assert not pilot.app.query_one("#summary").display
            assert "Project root:" not in pilot.app.query_one("#project-header").render().plain
            assert pilot.app.query_one("#ledger-source").display
            assert pilot.app.query_one("#footer-language").render().plain == "en"
            assert "Not inspected" in pilot.app.query_one("#ledger-source").render().plain
            await pilot.press("q")

    asyncio.run(scenario())


def test_status_row_selection_updates_context_detail(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(80, 24)) as pilot:
            await pilot.click("#ledger-runtime")
            detail = pilot.app.query_one("#context-detail").render().plain
            assert "MySQL database" in detail
            assert "No database connection has been made" in detail
            await pilot.press("q")

    asyncio.run(scenario())


def test_help_and_settings_are_visible_interactions(tmp_path: Path) -> None:
    from repoevidence.interactive.app import HelpScreen, RepoEvidenceApp, SettingsScreen

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(80, 24)) as pilot:
            await pilot.click("#help-action")
            assert isinstance(pilot.app.screen, HelpScreen)
            assert "Inspect source" in pilot.app.screen.query_one("#help-copy").render().plain
            assert "Keyboard" in pilot.app.screen.query_one("#help-shortcuts").render().plain
            await pilot.press("escape")
            await pilot.click("#settings-action")
            assert isinstance(pilot.app.screen, SettingsScreen)
            assert pilot.app.screen.query_one("#language-select")
            assert pilot.app.screen.query_one("#settings-feedback")
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(scenario())


def test_language_selector_re_renders_workspace_without_restarting(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp, SettingsScreen

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(80, 24)) as pilot:
            await pilot.click("#settings-action")
            assert isinstance(pilot.app.screen, SettingsScreen)
            select = pilot.app.screen.query_one("#language-select")
            select.value = "zh-CN"
            await pilot.pause()
            assert pilot.app.language == "zh-CN"
            assert pilot.app.controller.language == "zh-CN"
            await pilot.press("escape")
            assert "检查源码" in pilot.app.query_one("#primary-action").label.plain
            assert "项目状态" in pilot.app.query_one("#ledger-title").render().plain
            detail = pilot.app.query_one("#context-detail").render().plain
            assert "源码尚未检查" in detail
            assert "Outcome:" not in detail
            assert "下一步：" in detail
            await pilot.press("q")

    asyncio.run(scenario())


def test_open_settings_relabels_immediately_when_language_changes(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp, SettingsScreen

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(80, 24)) as pilot:
            await pilot.click("#settings-action")
            assert isinstance(pilot.app.screen, SettingsScreen)
            pilot.app.screen.query_one("#language-select").value = "zh-CN"
            await pilot.pause()
            assert "界面语言" in pilot.app.screen.query_one(
                "#settings-language-label"
            ).render().plain
            assert "返回" in pilot.app.screen.query_one("#settings-close").label.plain
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(scenario())


def test_workspace_survives_supported_terminal_widths(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        for size in ((40, 24), (60, 24), (80, 24), (100, 30), (120, 40)):
            async with RepoEvidenceApp(
                context,
                projection,
                language="en",
                settings=UserSettings(),
            ).run_test(size=size) as pilot:
                for item_id in ("source", "runtime", "comparison", "report"):
                    item = pilot.app.query_one(f"#ledger-{item_id}")
                    assert item.display
                    assert item.region.width <= size[0]
                assert pilot.app.query_one("#primary-action").display
                await pilot.press("q")

    asyncio.run(scenario())


def test_theme_and_reduced_motion_settings_are_real_controls(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp, SettingsScreen

    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(80, 24)) as pilot:
            await pilot.click("#settings-action")
            assert isinstance(pilot.app.screen, SettingsScreen)
            pilot.app.screen.query_one("#theme-select").value = "light"
            pilot.app.screen.query_one("#reduced-motion-select").value = True
            await pilot.pause()
            assert pilot.app.has_class("theme-light")
            assert pilot.app.has_class("reduced-motion")
            await pilot.press("escape")
            await pilot.press("q")

    asyncio.run(scenario())


def test_no_color_workspace_keeps_textual_semantics(tmp_path: Path, monkeypatch) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    monkeypatch.setenv("NO_COLOR", "1")
    _, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(80, 24)) as pilot:
            assert pilot.app.no_color
            assert pilot.app.native_ansi_color
            assert "NoColor" in [type(filter).__name__ for filter in pilot.app._filters]
            assert "Monochrome" not in [
                type(filter).__name__ for filter in pilot.app._filters
            ]
            assert "Source" in pilot.app.query_one("#ledger-source").render().plain
            assert pilot.app.query_one("#primary-action").display
            await pilot.press("q")

    asyncio.run(scenario())


def test_worker_success_updates_running_state_and_protects_quit(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    started = threading.Event()
    release = threading.Event()

    class Controller:
        def execute(self, action: str, *, listener):
            listener(
                OperationEvent(
                    "op-success",
                    action,
                    "execute",
                    "started",
                    1.0,
                )
            )
            started.set()
            while not release.is_set():
                time.sleep(0.01)
            listener(
                OperationEvent(
                    "op-success",
                    action,
                    "execute",
                    "completed",
                    2.0,
                )
            )
            return WorkspaceOperationResult(
                action,
                SimpleNamespace(summary=SimpleNamespace(errors=())),
            )

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
            controller=Controller(),
        ).run_test(size=(80, 24)) as pilot:
            await pilot.click("#primary-action")
            for _ in range(20):
                await pilot.pause(0.01)
                if started.is_set():
                    break
            assert pilot.app._running_action == "source.inspect"
            assert "Working" in pilot.app.query_one("#ledger-source").render().plain
            await pilot.press("q")
            assert pilot.app._running_action == "source.inspect"
            release.set()
            for _ in range(50):
                await pilot.pause(0.01)
                if pilot.app._running_action is None:
                    break
            assert pilot.app._running_action is None
            assert any("completed" in item for item in pilot.app.activity)
            assert not any("started" in item for item in pilot.app.activity)
            assert sum("completed" in item for item in pilot.app.activity) == 1
            await pilot.press("q")

    asyncio.run(scenario())


def test_slow_operation_shows_real_elapsed_activity(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    started = threading.Event()
    release = threading.Event()

    class Controller:
        def execute(self, action: str, *, listener):
            listener(
                OperationEvent(
                    operation_id="slow",
                    operation_kind=action,
                    phase_id="inspect",
                    event_kind="started",
                    monotonic_timestamp=1.0,
                )
            )
            started.set()
            release.wait(timeout=2)
            listener(
                OperationEvent(
                    operation_id="slow",
                    operation_kind=action,
                    phase_id="inspect",
                    event_kind="completed",
                    monotonic_timestamp=2.0,
                    safe_metadata={"elapsed_ms": 470},
                )
            )
            return WorkspaceOperationResult(
                action,
                SimpleNamespace(summary=SimpleNamespace(errors=())),
            )

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
            controller=Controller(),
        ).run_test(size=(100, 30)) as pilot:
            await pilot.click("#primary-action")
            for _ in range(50):
                await pilot.pause(0.01)
                if started.is_set():
                    break
            await pilot.pause(0.45)
            activity = pilot.app.query_one("#activity-log").render().plain
            assert "running" in activity
            assert "Inspect source" in activity
            release.set()
            for _ in range(80):
                await pilot.pause(0.01)
                if pilot.app._running_action is None:
                    break
            assert any("0.5s" in item for item in pilot.app.activity)
            await pilot.press("q")

    asyncio.run(scenario())


def test_worker_failure_stays_visible_and_can_be_recovered(tmp_path: Path) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)

    class Controller:
        def execute(self, action: str, *, listener):
            listener(OperationEvent("op-failure", action, "execute", "started", 1.0))
            listener(
                OperationEvent(
                    "op-failure",
                    action,
                    "execute",
                    "failed",
                    1.2,
                    {"error_type": "ExpectedFailure"},
                )
            )
            raise RuntimeError("secret-value-must-not-be-rendered")

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
            controller=Controller(),
        ).run_test(size=(80, 24)) as pilot:
            await pilot.click("#primary-action")
            for _ in range(50):
                await pilot.pause(0.01)
                if pilot.app._running_action is None:
                    break
            assert pilot.app._running_action is None
            assert any("failed" in item for item in pilot.app.activity)
            assert not any("started" in item for item in pilot.app.activity)
            assert sum("failed" in item for item in pilot.app.activity) == 1
            detail = pilot.app.query_one("#context-detail").render().plain
            technical = pilot.app.query_one("#technical-details")
            technical.query_one("CollapsibleTitle").focus()
            await pilot.press("enter")
            await pilot.pause()
            assert "ExpectedFailure" in technical.query_one(
                "#technical-details-copy"
            ).render().plain
            assert "secret-value-must-not-be-rendered" not in detail
            await pilot.press("q")

    asyncio.run(scenario())


def test_domain_failure_is_recorded_as_failed_activity_after_artifact_write(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    root, context, projection = _fresh_app_inputs(tmp_path)

    class Controller:
        def execute(self, action: str, *, listener):
            listener(OperationEvent("mysql-failed", action, "verify", "started", 1.0))
            result = VerificationResult(
                verifier="mysql",
                repository_root=str(root.resolve()),
                metadata=VerificationMetadata(
                    tool_version=__version__,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    observed_at=None,
                ),
                errors=[
                    VerificationError(
                        code="mysql_connection_failed",
                        message="safe technical detail",
                    )
                ],
            )
            artifact = root / ".repoevidence/verification/mysql.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
            listener(
                OperationEvent(
                    "mysql-failed",
                    action,
                    "verify",
                    "completed",
                    2.0,
                    {"elapsed_ms": 1000},
                )
            )
            return WorkspaceOperationResult(action, SimpleNamespace())

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
            controller=Controller(),
        ).run_test(size=(100, 30)) as pilot:
            pilot.app._start_operation("runtime.verify_mysql")
            for _ in range(80):
                await pilot.pause(0.01)
                if pilot.app._running_action is None:
                    break
            assert pilot.app._running_action is None
            assert any("failed" in item for item in pilot.app.activity)
            assert not any("Verify MySQL completed" in item for item in pilot.app.activity)
            assert not any("started" in item for item in pilot.app.activity)
            assert sum("failed" in item for item in pilot.app.activity) == 1
            assert pilot.app.projection.runtime.operation.value == "failed"
            await pilot.press("q")

    asyncio.run(scenario())


def test_mysql_action_requires_effect_preview_and_explicit_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from repoevidence.interactive.app import MySQLConfirmationScreen, RepoEvidenceApp

    _, context, projection = _fresh_app_inputs(tmp_path)
    secret = "mysql-password-value-must-not-render"
    monkeypatch.setenv("REPOEVIDENCE_MYSQL_HOST", "db.example")
    monkeypatch.setenv("REPOEVIDENCE_MYSQL_PORT", "3306")
    monkeypatch.setenv("REPOEVIDENCE_MYSQL_USER", "readonly")
    monkeypatch.setenv("REPOEVIDENCE_MYSQL_PASSWORD", secret)
    monkeypatch.setenv("REPOEVIDENCE_MYSQL_DATABASE", "service")
    calls: list[str] = []

    class Controller:
        def execute(self, action: str, *, listener):
            calls.append(action)
            listener(OperationEvent("mysql", action, "execute", "started", 1.0))
            listener(OperationEvent("mysql", action, "execute", "completed", 1.1))
            return WorkspaceOperationResult(action, SimpleNamespace())

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
            controller=Controller(),
        ).run_test(size=(100, 30)) as pilot:
            await pilot.click("#ledger-runtime")
            assert "Verify MySQL" in pilot.app.query_one("#primary-action").label.plain
            await pilot.click("#primary-action")
            assert isinstance(pilot.app.screen, MySQLConfirmationScreen)
            assert pilot.app.screen.query_one("#mysql-cancel").has_focus
            preview = "\n".join(
                (
                    pilot.app.screen.query_one("#mysql-confirmation-copy").render().plain,
                    pilot.app.screen.query_one("#mysql-confirmation-config").render().plain,
                )
            )
            assert "PASSWORD configured" in preview
            assert secret not in preview
            await pilot.click("#mysql-cancel")
            assert calls == []
            await pilot.click("#primary-action")
            await pilot.click("#mysql-confirm")
            for _ in range(50):
                await pilot.pause(0.01)
                if pilot.app._running_action is None:
                    break
            assert calls == ["runtime.verify_mysql"]
            assert pilot.app._running_action is None
            assert secret not in "\n".join(pilot.app.activity)
            await pilot.press("q")

    asyncio.run(scenario())


def test_default_workspace_controller_runs_inspect_and_refreshes_projection(
    tmp_path: Path,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    root, context, projection = _fresh_app_inputs(tmp_path)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            await pilot.click("#primary-action")
            for _ in range(300):
                await pilot.pause(0.01)
                if pilot.app._running_action is None:
                    break
            assert pilot.app._running_action is None
            assert (root / ".repoevidence/evidence.json").is_file()
            assert (root / ".repoevidence/report/index.html").is_file()
            assert (root / ".repoevidence/report/manifest.json").is_file()
            assert pilot.app.projection.source.freshness.value == "uncertain"
            assert any("completed" in item for item in pilot.app.activity)
            await pilot.press("q")

    asyncio.run(scenario())


def test_report_is_not_opened_after_generation_but_explicit_open_uses_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from repoevidence.interactive.app import RepoEvidenceApp

    root, context, projection = _fresh_app_inputs(tmp_path)
    opened: list[str] = []

    def browser_open(url: str) -> bool:
        opened.append(url)
        return False

    monkeypatch.setattr("repoevidence.application.webbrowser.open", browser_open)

    async def scenario() -> None:
        async with RepoEvidenceApp(
            context,
            projection,
            language="en",
            settings=UserSettings(),
        ).run_test(size=(100, 30)) as pilot:
            await pilot.click("#primary-action")
            for _ in range(300):
                await pilot.pause(0.01)
                if pilot.app._running_action is None:
                    break
            assert opened == []
            await pilot.click("#ledger-report")
            assert "Open report" in pilot.app.query_one("#primary-action").label.plain
            await pilot.click("#primary-action")
            for _ in range(100):
                await pilot.pause(0.01)
                if pilot.app._running_action is None:
                    break
            assert len(opened) == 1
            assert str(root / ".repoevidence/report/index.html") in opened[0]
            assert any("browser integration was unavailable" in item for item in pilot.app.activity)
            await pilot.press("q")

    asyncio.run(scenario())
