"""Persistent, read-only Textual workspace shell.

This module is the presentation layer for the workspace projection.  It is
intentionally not imported by the one-shot CLI until interactive routing has
already been selected.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Click, Resize
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
)
from textual.worker import Worker, WorkerState

from repoevidence.assessment import assess_repository
from repoevidence.i18n import Language, message, resolve_language
from repoevidence.operations import (
    OperationEvent,
    WorkspaceOperationResult,
    WorkspaceOperationService,
)
from repoevidence.project_context import ProjectContext, discover_project_context
from repoevidence.report_manifest import assess_report
from repoevidence.user_config import UserSettings, load_user_settings, save_user_settings
from repoevidence.workspace import (
    DomainOutcome,
    Freshness,
    WorkspaceCheck,
    WorkspaceProjection,
    WorkspaceSession,
    build_workspace_projection,
)


class HelpScreen(ModalScreen[None]):
    """Discoverable help surface, available without learning a command syntax."""

    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, language: Language) -> None:
        super().__init__()
        self.language = language

    def compose(self) -> ComposeResult:
        yield Container(
            Static(message("workspace.help.title", self.language), id="help-title"),
            Static(message("workspace.help.copy", self.language), id="help-copy"),
            Static(
                message("workspace.help.shortcuts", self.language),
                id="help-shortcuts",
                classes="muted",
            ),
            Button(message("workspace.settings.close", self.language), id="help-close"),
            id="help-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.dismiss()

    def action_dismiss(self) -> None:
        self.dismiss()


class SettingsScreen(ModalScreen[None]):
    """User-level settings surface with real selectors instead of hidden commands."""

    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, app: "RepoEvidenceApp") -> None:
        super().__init__()
        self.workspace_app = app

    def compose(self) -> ComposeResult:
        settings = self.workspace_app.settings
        yield Container(
            Static(
                message("workspace.settings.title", self.workspace_app.language),
                id="settings-title",
            ),
            Static(
                message("workspace.settings.note", self.workspace_app.language),
                id="settings-note",
                classes="muted",
            ),
            Label(
                message("workspace.settings.language", self.workspace_app.language),
                id="settings-language-label",
            ),
            Select(
                self._language_options(),
                value=self.workspace_app.language,
                allow_blank=False,
                id="language-select",
            ),
            Label(
                message("workspace.settings.theme", self.workspace_app.language),
                id="settings-theme-label",
            ),
            Select(
                self._theme_options(),
                value=settings.theme,
                allow_blank=False,
                id="theme-select",
            ),
            Label(
                message("workspace.settings.interaction", self.workspace_app.language),
                id="settings-interaction-label",
            ),
            Select(
                self._interaction_options(),
                value=settings.interaction,
                allow_blank=False,
                id="interaction-select",
            ),
            Checkbox(
                message("workspace.settings.reduced_motion", self.workspace_app.language),
                value=settings.reduced_motion,
                id="reduced-motion-select",
            ),
            Static("", id="settings-feedback", classes="settings-feedback"),
            Button(
                message("workspace.settings.close", self.workspace_app.language),
                id="settings-close",
            ),
            id="settings-dialog",
        )

    def _language_options(self) -> tuple[tuple[str, str], ...]:
        return (("English", "en"), ("简体中文", "zh-CN"))

    def _theme_options(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                message(f"workspace.settings.value.{value}", self.workspace_app.language),
                value,
            )
            for value in ("auto", "dark", "light")
        )

    def _interaction_options(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                message(f"workspace.settings.value.{value}", self.workspace_app.language),
                value,
            )
            for value in ("auto", "workspace", "plain")
        )

    def refresh_labels(self) -> None:
        """Redraw the open settings surface after a live language change."""

        self.query_one("#settings-title", Static).update(
            message("workspace.settings.title", self.workspace_app.language)
        )
        self.query_one("#settings-note", Static).update(
            message("workspace.settings.note", self.workspace_app.language)
        )
        self.query_one("#settings-language-label", Label).update(
            message("workspace.settings.language", self.workspace_app.language)
        )
        self.query_one("#settings-theme-label", Label).update(
            message("workspace.settings.theme", self.workspace_app.language)
        )
        self.query_one("#settings-interaction-label", Label).update(
            message("workspace.settings.interaction", self.workspace_app.language)
        )
        self.query_one("#reduced-motion-select", Checkbox).label = message(
            "workspace.settings.reduced_motion", self.workspace_app.language
        )
        self.query_one("#settings-close", Button).label = message(
            "workspace.settings.close", self.workspace_app.language
        )
        self.query_one("#theme-select", Select).set_options(self._theme_options())
        self.query_one("#interaction-select", Select).set_options(self._interaction_options())

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value is Select.NULL:
            return
        value = str(event.value)
        if event.select.id == "language-select":
            self.workspace_app.set_language(resolve_language(value))
        elif event.select.id == "theme-select":
            self.workspace_app.set_theme(value)
        elif event.select.id == "interaction-select":
            self.workspace_app.set_interaction(value)
        self.query_one("#settings-feedback", Static).update(
            message("workspace.settings.saved", self.workspace_app.language)
        )

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "reduced-motion-select":
            self.workspace_app.set_reduced_motion(event.value)
            self.query_one("#settings-feedback", Static).update(
                message("workspace.settings.saved", self.workspace_app.language)
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-close":
            self.dismiss()

    def action_dismiss(self) -> None:
        self.dismiss()


class MySQLConfirmationScreen(ModalScreen[None]):
    """Effect preview shown immediately before the only database connection."""

    BINDINGS = [("escape", "dismiss", "Cancel")]
    _ENV_KEYS = (
        ("HOST", "REPOEVIDENCE_MYSQL_HOST"),
        ("PORT", "REPOEVIDENCE_MYSQL_PORT"),
        ("USER", "REPOEVIDENCE_MYSQL_USER"),
        ("PASSWORD", "REPOEVIDENCE_MYSQL_PASSWORD"),
        ("DATABASE", "REPOEVIDENCE_MYSQL_DATABASE"),
    )

    def __init__(self, workspace_app: "RepoEvidenceApp") -> None:
        super().__init__()
        self.workspace_app = workspace_app

    def compose(self) -> ComposeResult:
        configured = message("workspace.mysql.preview.configured", self.workspace_app.language)
        missing = message("workspace.mysql.preview.missing", self.workspace_app.language)
        config_lines = [
            f"{name:<8} {configured if os.environ.get(key) else missing}"
            for name, key in self._ENV_KEYS
        ]
        yield Container(
            Static(
                message("workspace.mysql.preview.title", self.workspace_app.language),
                id="mysql-confirmation-title",
            ),
            Static(
                message("workspace.mysql.preview.copy", self.workspace_app.language),
                id="mysql-confirmation-copy",
            ),
            Static("\n".join(config_lines), id="mysql-confirmation-config"),
            Horizontal(
                Button(
                    message("workspace.mysql.preview.cancel", self.workspace_app.language),
                    id="mysql-cancel",
                ),
                Button(
                    message("workspace.mysql.preview.confirm", self.workspace_app.language),
                    variant="primary",
                    id="mysql-confirm",
                ),
                id="mysql-confirmation-actions",
            ),
            id="mysql-confirmation",
        )

    def on_mount(self) -> None:
        self.query_one("#mysql-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mysql-cancel":
            self.dismiss()
        elif event.button.id == "mysql-confirm":
            self.workspace_app.start_mysql_verification()
            self.dismiss()

    def action_dismiss(self) -> None:
        self.dismiss()


class RepoEvidenceApp(App[None]):
    """The stable five-region project workspace."""

    TITLE = "RepoEvidence"
    CSS = """
    RepoEvidenceApp {
        background: #11171a;
        color: #e7f2ef;
        &.theme-light {
            background: #f4f8f7;
            color: #13201d;
        }
        &.theme-light Screen {
            background: #f4f8f7;
            color: #13201d;
        }
        &.theme-dark Screen {
            background: #11171a;
            color: #e7f2ef;
        }
        &.reduced-motion * {
            transition: none;
        }
    }

    Screen {
        background: #11171a;
        color: #e7f2ef;
    }

    #workspace {
        height: 1fr;
        width: 1fr;
        padding: 0 2;
    }

    #project-header {
        height: auto;
        min-height: 4;
        padding: 0 1;
        color: #e7f2ef;
        text-style: bold;
    }

    #summary {
        height: auto;
        min-height: 2;
        padding: 0 1;
        color: #a7bbb6;
    }

    #body {
        height: 1fr;
        layout: horizontal;
        margin-top: 1;
    }

    #ledger-pane, #detail-pane {
        height: 1fr;
        padding: 0 1;
    }

    #ledger-pane {
        width: 46%;
        min-width: 29;
    }

    #detail-pane {
        width: 54%;
        margin-left: 1;
        border: round #2a766c;
    }

    #ledger-title, #detail-heading, #activity-heading {
        height: auto;
        padding: 0;
        color: #5ed6be;
        text-style: bold;
    }

    #ledger {
        height: 1fr;
        background: transparent;
        border: none;
    }

    #ledger > ListItem {
        height: auto;
        min-height: 2;
        padding: 0 1;
        margin-bottom: 0;
        background: transparent;
    }

    #ledger > ListItem.-highlight {
        background: #1b3a38;
        color: #ffffff;
        text-style: bold;
    }

    #ledger:focus > ListItem.-highlight {
        background: #21685e;
        color: #ffffff;
    }

    #context-detail {
        height: 1fr;
        padding: 0 1;
        color: #d4e3df;
        overflow-y: auto;
    }

    #actions {
        height: auto;
        min-height: 3;
        align: left middle;
        padding: 0;
    }

    #actions Button {
        margin-right: 1;
    }

    #footer-actions {
        height: 3;
        align: left middle;
    }

    #footer-actions Button {
        margin-right: 1;
    }

    #primary-action {
        background: #168c7a;
        color: #ffffff;
        text-style: bold;
    }

    #secondary-action {
        color: #5ed6be;
    }

    #activity {
        height: 2;
        padding: 0 1;
        margin-top: 1;
        border-top: solid #28423f;
        color: #a7bbb6;
        overflow-y: hidden;
    }

    #activity-heading {
        padding-top: 0;
        padding-bottom: 0;
        color: #a7bbb6;
        text-style: none;
    }

    Footer {
        background: #0c1113;
        color: #c4d3cf;
    }

    .muted {
        color: #8da39d;
    }

    ModalScreen {
        align: center middle;
        background: #000000 70%;
    }

    #help-dialog, #settings-dialog, #mysql-confirmation {
        width: 72%;
        max-width: 78;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: #172321;
        border: round #5ed6be;
    }

    #help-title, #settings-title {
        height: auto;
        padding-bottom: 1;
        color: #5ed6be;
        text-style: bold;
    }

    #help-copy {
        height: auto;
        padding-bottom: 1;
    }

    #help-shortcuts {
        height: auto;
        padding-bottom: 1;
    }

    #settings-dialog Label {
        height: auto;
        padding-top: 1;
        color: #a7bbb6;
    }

    #settings-dialog Select {
        width: 1fr;
    }

    #settings-dialog Checkbox {
        margin-top: 1;
        margin-bottom: 1;
    }

    #mysql-confirmation-title {
        height: auto;
        padding-bottom: 1;
        color: #5ed6be;
        text-style: bold;
    }

    #mysql-confirmation-copy, #mysql-confirmation-config {
        height: auto;
        padding-bottom: 1;
    }

    #mysql-confirmation-config {
        color: #d4e3df;
    }

    #mysql-confirmation-actions {
        height: 3;
        align: right middle;
    }

    RepoEvidenceApp:ansi Screen, RepoEvidenceApp:ansi ModalScreen {
        background: ansi_default;
        color: ansi_default;
    }

    RepoEvidenceApp:ansi #ledger > ListItem.-highlight,
    RepoEvidenceApp:ansi #ledger:focus > ListItem.-highlight,
    RepoEvidenceApp:ansi #primary-action {
        background: ansi_default;
        color: ansi_default;
        text-style: reverse;
    }

    RepoEvidenceApp.narrow #workspace {
        padding: 0 1;
    }

    RepoEvidenceApp.narrow #body {
        layout: vertical;
    }

    RepoEvidenceApp.narrow #ledger-pane {
        width: 1fr;
        min-width: 0;
        height: 10;
    }

    RepoEvidenceApp.narrow #detail-pane {
        width: 1fr;
        margin-left: 0;
        margin-top: 1;
    }

    RepoEvidenceApp.narrow #activity {
        display: none;
    }

    RepoEvidenceApp.narrow #ledger-pane {
        height: 8;
    }

    RepoEvidenceApp.narrow #detail-pane {
        height: 3;
        padding: 0;
        border: none;
    }

    RepoEvidenceApp.narrow #detail-heading,
    RepoEvidenceApp.narrow #context-detail,
    RepoEvidenceApp.narrow #secondary-action {
        display: none;
    }

    RepoEvidenceApp.narrow #actions {
        height: 3;
        min-height: 3;
    }

    RepoEvidenceApp.very-narrow #project-header {
        min-height: 3;
    }

    RepoEvidenceApp.very-narrow #summary {
        max-height: 3;
        overflow-y: hidden;
    }

    RepoEvidenceApp.very-narrow #ledger-pane {
        height: 8;
    }

    RepoEvidenceApp.very-narrow #actions {
        layout: vertical;
        min-height: 5;
    }

    RepoEvidenceApp.very-narrow #actions Button {
        width: 1fr;
        margin-right: 0;
    }

    RepoEvidenceApp.very-narrow #context-detail {
        max-height: 5;
    }

    /* Textual 8 does responsive layout through classes; these selectors are
       toggled from on_resize so the behavior is also testable headlessly. */
    RepoEvidenceApp.narrow, RepoEvidenceApp.very-narrow {
        color: #e7f2ef;
    }

    /* Keep the terminal shell functional in very small viewports. */
    RepoEvidenceApp.very-narrow #workspace {
        padding: 0 1;
    }

    /*
    @media (max-width: 69) {
        #workspace {
            padding: 0 1;
        }
        #body {
            layout: vertical;
        }
        #ledger-pane {
            width: 1fr;
            min-width: 0;
            height: 10;
        }
        #detail-pane {
            width: 1fr;
            margin-left: 0;
            margin-top: 1;
        }
        #activity {
            height: 3;
        }
    }

    @media (max-width: 49) {
        #project-header {
            min-height: 3;
        }
        #summary {
            max-height: 3;
            overflow-y: hidden;
        }
        #ledger-pane {
            height: 8;
        }
        #actions {
            layout: vertical;
            min-height: 5;
        }
        #actions Button {
            width: 1fr;
            margin-right: 0;
        }
        #context-detail {
            max-height: 5;
        }
    }
    */

    /* v2: quiet terminal hierarchy. The existing state colors remain
       semantic, but only the primary action and keyboard focus get strong
       emphasis. */
    #workspace {
        padding: 0 2;
    }

    #project-header {
        min-height: 3;
        padding: 0 1;
        color: #e7f2ef;
        text-style: none;
    }

    #summary {
        min-height: 1;
        padding: 0 1;
        color: #8da39d;
        text-style: none;
    }

    #summary.hidden {
        display: none;
    }

    #body {
        margin-top: 1;
    }

    #ledger-pane,
    #detail-pane {
        padding: 0 1;
    }

    #detail-pane {
        margin-left: 1;
        border: none;
        border-left: solid #2a3536;
        padding-left: 2;
    }

    #ledger-title,
    #detail-heading {
        color: #c4d3cf;
        text-style: bold;
    }

    #detail-heading {
        padding-bottom: 1;
    }

    #ledger > ListItem {
        padding: 0 1;
        border-left: solid transparent;
        color: #d4e3df;
    }

    #ledger > ListItem > Horizontal {
        height: auto;
        min-height: 2;
    }

    #ledger > ListItem.-highlight {
        background: #1a2527;
        color: #e7f2ef;
        text-style: none;
    }

    #ledger:focus > ListItem.-highlight {
        background: #263536;
        border-left: tall #63c9b5;
        color: #ffffff;
        text-style: bold;
    }

    #ledger > ListItem.selected-row {
        background: #1a2527;
        border-left: tall #49615c;
        color: #e7f2ef;
        text-style: none;
    }

    #ledger:focus > ListItem.selected-row {
        background: #263536;
        border-left: tall #63c9b5;
        color: #ffffff;
        text-style: bold;
    }

    .ledger-copy {
        height: auto;
        width: 1fr;
        padding-left: 1;
    }

    .status-marker {
        width: 2;
        color: #70827e;
        text-align: center;
    }

    #ledger:focus .status-marker {
        color: #a6b7b2;
    }

    #context-detail {
        padding: 0;
        color: #d4e3df;
    }

    #technical-details {
        height: auto;
        min-height: 1;
        margin-top: 1;
        padding: 0;
        border-top: solid #2a3536;
        background: transparent;
    }

    #technical-details > Contents {
        padding: 0 0 0 2;
    }

    #technical-details CollapsibleTitle {
        height: 1;
        padding: 0 1;
        color: #80908c;
        text-style: none;
    }

    #technical-details CollapsibleTitle:focus {
        background: #263c39;
        color: #e7f2ef;
        text-style: bold;
    }

    #technical-details-copy {
        height: auto;
        color: #9aa9a5;
    }

    #actions {
        min-height: 2;
        align: left middle;
        padding: 1 0 0 0;
    }

    #actions Button {
        height: 1;
        min-width: 0;
        margin-right: 2;
        padding: 0 1;
        border: none;
    }

    #primary-action {
        background: #287f70;
        color: #ffffff;
        text-style: bold;
    }

    #primary-action:focus {
        background: #36a18d;
        text-style: bold reverse;
    }

    #secondary-action {
        background: transparent;
        color: #9aa9a5;
        text-style: none;
    }

    #secondary-action:focus {
        color: #e7f2ef;
        text-style: reverse;
    }

    #activity {
        height: auto;
        min-height: 2;
        max-height: 6;
        padding: 1 1 0 1;
        margin-top: 1;
        border-top: solid #2a3536;
        color: #9aa9a5;
    }

    #activity.empty-activity {
        display: none;
    }

    #activity-heading {
        color: #80908c;
        text-style: none;
    }

    #footer-bar {
        height: 2;
        padding: 0 1;
        border-top: solid #2a3536;
        align: left middle;
    }

    #footer-status {
        width: 1fr;
        color: #80908c;
        overflow-x: hidden;
    }

    #footer-actions {
        width: auto;
        height: 1;
        align: right middle;
    }

    #footer-actions Button {
        height: 1;
        min-width: 0;
        margin-right: 1;
        padding: 0 1;
        border: none;
        background: transparent;
        color: #a8b5b1;
        text-style: none;
    }

    #quit-action {
        color: #968985;
    }

    #footer-actions Button:focus {
        background: #263c39;
        color: #ffffff;
        text-style: bold;
    }

    #footer-language {
        width: auto;
        padding-left: 1;
        color: #80908c;
    }

    .muted {
        color: #80908c;
    }

    ModalScreen {
        background: #000000 68%;
    }

    #help-dialog,
    #settings-dialog,
    #mysql-confirmation {
        width: 72%;
        max-width: 78;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: #172022;
        border: round #354345;
    }

    #help-title,
    #settings-title,
    #mysql-confirmation-title {
        color: #d6e3df;
        text-style: bold;
    }

    #help-copy {
        height: auto;
        padding: 1 0;
        color: #d4e3df;
    }

    #help-shortcuts {
        height: auto;
        padding-bottom: 1;
    }

    #settings-note {
        height: auto;
        padding: 1 0 0 0;
    }

    #settings-dialog Label {
        height: auto;
        padding-top: 1;
        color: #a8b5b1;
    }

    #settings-dialog Select {
        width: 1fr;
    }

    #settings-dialog Checkbox {
        margin-top: 1;
        margin-bottom: 0;
    }

    .settings-feedback {
        height: 1;
        padding-top: 1;
    }

    #mysql-confirmation-copy,
    #mysql-confirmation-config {
        height: auto;
        padding-bottom: 1;
    }

    #mysql-confirmation-config {
        color: #d4e3df;
    }

    #mysql-confirmation-actions {
        height: 1;
        align: right middle;
    }

    #mysql-confirmation-actions Button {
        height: 1;
        min-width: 0;
        border: none;
        margin-left: 1;
    }

    RepoEvidenceApp:ansi Screen,
    RepoEvidenceApp:ansi ModalScreen {
        background: ansi_default;
        color: ansi_default;
    }

    RepoEvidenceApp:ansi #ledger > ListItem.-highlight,
    RepoEvidenceApp:ansi #ledger:focus > ListItem.-highlight,
    RepoEvidenceApp:ansi #primary-action,
    RepoEvidenceApp:ansi #footer-actions Button:focus {
        background: ansi_default;
        color: ansi_default;
        text-style: reverse;
    }

    RepoEvidenceApp.narrow #workspace {
        padding: 0 1;
    }

    RepoEvidenceApp.narrow #detail-pane {
        margin-left: 0;
        margin-top: 1;
        border-left: none;
        padding-left: 0;
    }

    RepoEvidenceApp.narrow #footer-status {
        display: none;
    }

    RepoEvidenceApp.narrow #footer-bar {
        align: right middle;
    }

    RepoEvidenceApp.very-narrow #project-header {
        min-height: 3;
        max-height: 3;
        overflow-y: hidden;
    }

    RepoEvidenceApp.very-narrow #summary {
        display: none;
    }

    RepoEvidenceApp.very-narrow #detail-heading,
    RepoEvidenceApp.very-narrow #context-detail,
    RepoEvidenceApp.very-narrow #secondary-action {
        display: none;
    }

    RepoEvidenceApp.very-narrow #detail-pane {
        height: 3;
    }

    RepoEvidenceApp.very-narrow #actions {
        height: 3;
        min-height: 3;
        layout: vertical;
    }

    RepoEvidenceApp.very-narrow #actions Button {
        width: 1fr;
        margin-right: 0;
    }

    /* The collapsed disclosure keeps one compact row; reserve the remaining
       narrow detail height for the primary action instead of clipping it. */
    RepoEvidenceApp.narrow #detail-pane {
        height: 5;
        min-height: 5;
    }

    RepoEvidenceApp.very-narrow #detail-pane {
        height: 7;
        min-height: 7;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("?", "show_help", "Help"),
    ]

    def __init__(
        self,
        context: ProjectContext,
        projection: WorkspaceProjection,
        *,
        language: Language,
        settings: UserSettings,
        controller: Any | None = None,
        activity: tuple[str, ...] = (),
        persist_settings: bool = False,
    ) -> None:
        # Textual's default theme uses a monochrome true-color filter when
        # NO_COLOR is set.  That still emits grayscale SGR sequences.  Force
        # native ANSI mode so Textual's NoColor filter can remove color data
        # before the driver serializes a frame.
        super().__init__(ansi_color=True if os.environ.get("NO_COLOR") is not None else None)
        self.context = context
        self.projection = projection
        self.language = language
        self.settings = settings
        self.controller = controller or WorkspaceOperationService(
            str(context.project_root), language=language
        )
        self.activity = list(activity[-5:])
        self.persist_settings = persist_settings
        self.selected_id = projection.selected_id
        self.session: WorkspaceSession | None = None
        self._worker: Worker[WorkspaceOperationResult] | None = None
        self._running_action: str | None = None
        self._failed_action: str | None = None
        self._last_operation_result: WorkspaceOperationResult | None = None
        self._operation_error_type: str | None = None
        self._completed_elapsed: float | None = None
        self._running_since: float | None = None
        self._live_activity: str | None = None
        self._live_delay_timer: Any | None = None
        self._live_timer: Any | None = None
        self._apply_theme_class()

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self._header_text(), id="project-header"),
            Static(
                message("workspace.product.summary", self.language),
                id="summary",
                classes="onboarding" if self._show_onboarding() else "hidden",
            ),
            Horizontal(
                Vertical(
                    Static(message("workspace.ledger.title", self.language), id="ledger-title"),
                    ListView(
                        *self._ledger_items(),
                        initial_index=self._selected_index(),
                        id="ledger",
                    ),
                    id="ledger-pane",
                ),
                Vertical(
                    Static(message("workspace.detail.title", self.language), id="detail-heading"),
                    Static(self._human_detail_text(), id="context-detail"),
                    Collapsible(
                        Static(
                            self._technical_detail_text(),
                            markup=False,
                            id="technical-details-copy",
                        ),
                        title=message("workspace.detail.technical_details", self.language),
                        collapsed=True,
                        id="technical-details",
                    ),
                    Horizontal(
                        Button(
                            self._action_label(self._primary_button_action()),
                            variant="primary",
                            id="primary-action",
                        ),
                        Button(
                            self._action_label(self._secondary_button_action()),
                            variant="default",
                            id="secondary-action",
                        )
                        if self._secondary_button_action()
                        else Button("", id="secondary-action", disabled=True),
                        id="actions",
                    ),
                    id="detail-pane",
                ),
                id="body",
            ),
            Vertical(
                Static(message("workspace.detail.activity", self.language), id="activity-heading"),
                Static(self._activity_text(), id="activity-log"),
                id="activity",
                classes="" if self._activity_visible() else "empty-activity",
            ),
            Horizontal(
                Static(self._footer_status_text(), id="footer-status"),
                Horizontal(
                    Button(
                        message("workspace.action.settings", self.language),
                        id="settings-action",
                    ),
                    Button(message("workspace.action.help", self.language), id="help-action"),
                    Button(message("workspace.action.quit", self.language), id="quit-action"),
                    id="footer-actions",
                ),
                Static(self._language_label(), id="footer-language", classes="muted"),
                id="footer-bar",
            ),
            id="workspace",
        )

    def on_mount(self) -> None:
        self._update_responsive_classes()
        self._refresh_labels()
        self.query_one("#primary-action", Button).focus()

    def on_resize(self, event: Resize) -> None:
        del event
        self._update_responsive_classes()
        self.refresh(layout=True)

    def _update_responsive_classes(self) -> None:
        width = self.size.width
        was_very_narrow = self.has_class("very-narrow")
        if width < 70:
            self.add_class("narrow")
        else:
            self.remove_class("narrow")
        if width < 50:
            self.add_class("very-narrow")
        else:
            self.remove_class("very-narrow")
        if was_very_narrow != self.has_class("very-narrow") and self.is_mounted:
            self._refresh_labels()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen(self.language))

    def action_quit(self) -> None:
        if self._running_action is not None:
            self._record_activity(message("workspace.operation.protected_quit", self.language))
            self._refresh_labels()
            return
        self.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "help-action":
            self.action_show_help()
        elif button_id == "settings-action":
            self.push_screen(SettingsScreen(self))
        elif button_id == "quit-action":
            self.action_quit()
        elif button_id in {"primary-action", "secondary-action"}:
            action = (
                self._primary_button_action()
                if button_id == "primary-action"
                else self._secondary_button_action()
            )
            if action:
                self._invoke_action(action)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._select_item(event.item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._select_item(event.item)

    def on_click(self, event: Click) -> None:
        widget_id = getattr(event.widget, "id", None)
        if widget_id and widget_id.startswith("ledger-"):
            self._select_item_id(widget_id)

    def set_language(self, language: Language) -> None:
        self.language = language
        self.settings = UserSettings(
            language=language,
            theme=self.settings.theme,
            interaction=self.settings.interaction,
            reduced_motion=self.settings.reduced_motion,
        )
        if hasattr(self.controller, "language"):
            self.controller.language = language
        self._save_settings_safely()
        if self.is_mounted:
            self._refresh_labels()
        if isinstance(self.screen, SettingsScreen):
            self.screen.refresh_labels()

    def set_theme(self, theme: str) -> None:
        if theme not in {"auto", "dark", "light"}:
            return
        self.settings = UserSettings(
            language=self.settings.language,
            theme=theme,
            interaction=self.settings.interaction,
            reduced_motion=self.settings.reduced_motion,
        )
        self._apply_theme_class()
        self._save_settings_safely()

    def set_interaction(self, interaction: str) -> None:
        if interaction not in {"auto", "workspace", "plain"}:
            return
        self.settings = UserSettings(
            language=self.settings.language,
            theme=self.settings.theme,
            interaction=interaction,
            reduced_motion=self.settings.reduced_motion,
        )
        self._save_settings_safely()

    def set_reduced_motion(self, reduced_motion: bool) -> None:
        self.settings = UserSettings(
            language=self.settings.language,
            theme=self.settings.theme,
            interaction=self.settings.interaction,
            reduced_motion=reduced_motion,
        )
        self._apply_theme_class()
        self._save_settings_safely()

    def _refresh_labels(self) -> None:
        self.query_one("#project-header", Static).update(self._header_text())
        self.query_one("#summary", Static).update(
            message("workspace.product.summary", self.language)
        )
        summary = self.query_one("#summary", Static)
        if self._show_onboarding():
            summary.remove_class("hidden")
            summary.add_class("onboarding")
        else:
            summary.remove_class("onboarding")
            summary.add_class("hidden")
        self.query_one("#ledger-title", Static).update(
            message("workspace.ledger.title", self.language)
        )
        self.query_one("#detail-heading", Static).update(
            message("workspace.detail.title", self.language)
        )
        for check_id in ("source", "runtime", "comparison", "report"):
            self.query_one(f"#ledger-{check_id}", Static).update(
                self._row_text(getattr(self.projection, check_id))
            )
            self.query_one(f"#ledger-status-{check_id}", Static).update(
                self._status_token(getattr(self.projection, check_id))
            )
        self.query_one("#context-detail", Static).update(self._human_detail_text())
        technical = self.query_one("#technical-details", Collapsible)
        technical.title = message("workspace.detail.technical_details", self.language)
        technical.query_one("#technical-details-copy", Static).update(
            self._technical_detail_text()
        )
        self.query_one("#activity-heading", Static).update(
            message("workspace.detail.activity", self.language)
        )
        self.query_one("#activity-log", Static).update(self._activity_text())
        activity = self.query_one("#activity", Vertical)
        if self._activity_visible():
            activity.remove_class("empty-activity")
        else:
            activity.add_class("empty-activity")
        primary_action = self._primary_button_action()
        secondary_action = self._secondary_button_action()
        primary_button = self.query_one("#primary-action", Button)
        primary_button.label = self._action_label(primary_action)
        primary_button.disabled = primary_action is None or self._running_action is not None
        secondary = self.query_one("#secondary-action", Button)
        if secondary_action:
            secondary.label = self._action_label(secondary_action)
            secondary.disabled = self._running_action is not None
        else:
            secondary.label = ""
            secondary.disabled = True
        self.query_one("#settings-action", Button).label = message(
            "workspace.action.settings", self.language
        )
        self.query_one("#help-action", Button).label = message(
            "workspace.action.help", self.language
        )
        self.query_one("#quit-action", Button).label = message(
            "workspace.action.quit", self.language
        )
        self.query_one("#footer-status", Static).update(self._footer_status_text())
        self.query_one("#footer-language", Static).update(self._language_label())

    def _select_item(self, item: ListItem | None) -> None:
        if item is None or item.id is None:
            return
        self._select_item_id(item.id)

    def _select_item_id(self, item_id: str) -> None:
        selected = item_id.removeprefix("row-").removeprefix("ledger-")
        if selected not in {"source", "runtime", "comparison", "report"}:
            return
        self.selected_id = selected
        for check_id in ("source", "runtime", "comparison", "report"):
            row = self.query_one(f"#row-{check_id}", ListItem)
            if check_id == selected:
                row.add_class("selected-row")
            else:
                row.remove_class("selected-row")
        self._refresh_labels()

    def _invoke_action(self, action: str) -> None:
        if action == "runtime.verify_mysql":
            self.push_screen(MySQLConfirmationScreen(self))
            return
        if action == "view.finding":
            self._select_item_id("comparison")
            return
        if action.startswith("view."):
            self._select_item_id(action.removeprefix("view."))
            return
        if action == "help.open":
            self.action_show_help()
            return
        if action == "settings.open":
            self.push_screen(SettingsScreen(self))
            return
        if action == "app.quit":
            self.action_quit()
            return
        if hasattr(self.controller, "execute"):
            self._start_operation(action)
            return
        if hasattr(self.controller, "invoke"):
            self.controller.invoke(action)
            return
        self._record_activity(message("workspace.error.action_unavailable", self.language))
        self._refresh_labels()

    def start_mysql_verification(self) -> None:
        """Start only after the confirmation screen's explicit confirm button."""

        self._start_operation("runtime.verify_mysql")

    def _start_operation(self, action: str) -> None:
        if self._running_action is not None:
            self._record_activity(message("workspace.operation.running", self.language))
            self._refresh_labels()
            return
        self._running_action = action
        self._failed_action = None
        self._operation_error_type = None
        self._last_operation_result = None
        self._completed_elapsed = None
        self._running_since = time.monotonic()
        self._live_activity = None
        self._stop_live_timers()
        self.projection = replace(
            self.projection,
            active_operation=action,
            active_phase="execute",
        )
        self._refresh_labels()
        self._live_delay_timer = self.set_timer(0.35, self._show_live_activity)
        self._worker = self.run_worker(
            lambda: self._run_operation(action),
            name=action,
            description=self._action_label(action),
            exit_on_error=False,
            thread=True,
        )

    def _run_operation(self, action: str) -> WorkspaceOperationResult:
        result = self.controller.execute(action, listener=self._receive_operation_event)
        self._last_operation_result = result
        return result

    def _receive_operation_event(self, event: OperationEvent) -> None:
        if threading.get_ident() == self._thread_id:
            self._handle_operation_event(event)
        else:
            self.call_from_thread(self._handle_operation_event, event)

    def _handle_operation_event(self, event: OperationEvent) -> None:
        if self._running_action != event.operation_kind:
            return
        self.projection = replace(
            self.projection,
            active_operation=self._running_action,
            active_phase=event.phase_id,
        )
        if event.event_kind == "started":
            self._running_since = self._running_since or time.monotonic()
            self.projection = replace(self.projection, active_phase=event.phase_id)
        elif event.event_kind == "completed":
            # Completion means the service returned an artifact result.  The
            # domain outcome is known only after the projection is rebuilt.
            self._completed_elapsed = _event_elapsed(event, self._elapsed_seconds())
        elif event.event_kind == "failed":
            self._operation_error_type = str(
                event.safe_metadata.get("error_type", "OperationError")
            )
        self._refresh_labels()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if self._worker is None or event.worker is not self._worker:
            return
        if event.state is WorkerState.SUCCESS:
            self._finish_operation(success=True)
        elif event.state in {WorkerState.ERROR, WorkerState.CANCELLED}:
            if self._operation_error_type is None:
                error = event.worker.error
                self._operation_error_type = type(error).__name__ if error else "OperationError"
            self._finish_operation(success=False)

    def _finish_operation(self, *, success: bool) -> None:
        action = self._running_action
        result = self._last_operation_result
        if action is None:
            return
        elapsed = self._completed_elapsed or self._elapsed_seconds()
        self._stop_live_timers()
        self._running_since = None
        self._live_activity = None
        if success and action == "source.inspect" and _inspect_succeeded(result):
            try:
                self.context = discover_project_context(
                    self.context.project_root,
                    cwd=self.context.opened_from,
                )
            except (OSError, ValueError):
                pass
            self.session = WorkspaceSession(
                inspected_source_at=datetime.now(timezone.utc),
                inspected_project_root=self.context.project_root,
                inspected_head=self.context.git.commit,
                inspected_status_fingerprint=self.context.git.status_fingerprint,
            )
        self._running_action = None
        self.projection = replace(self.projection, active_operation=None, active_phase=None)
        if success:
            self._refresh_projection_from_disk()
            if self._operation_targets_failed_check(action):
                self._failed_action = action
                self._record_activity(
                    message(
                        "workspace.activity.failed_timed",
                        self.language,
                        label=self._action_label(action),
                        elapsed=_format_elapsed(elapsed),
                    )
                )
            else:
                self._record_activity(
                    message(
                        "workspace.activity.completed_timed",
                        self.language,
                        label=self._action_label(action),
                        elapsed=_format_elapsed(elapsed),
                    )
                )
            if action == "report.open" and result is not None:
                value = result.value
                if getattr(value, "browser_opened", False):
                    self._record_activity(
                        message("workspace.activity.report_opened", self.language)
                    )
                else:
                    self._record_activity(
                        message(
                            "workspace.activity.report_fallback",
                            self.language,
                            path=getattr(value, "report_path", ""),
                        )
                    )
        else:
            self._failed_action = action
            self._record_activity(
                message(
                    "workspace.activity.failed_timed",
                    self.language,
                    label=self._action_label(action),
                    elapsed=_format_elapsed(elapsed),
                )
            )
            self._refresh_projection_from_disk()
        self._completed_elapsed = None
        self._refresh_labels()

    def _operation_targets_failed_check(self, action: str) -> bool:
        check_id = {
            "source.inspect": "source",
            "source.scan_only": "source",
            "runtime.verify_mysql": "runtime",
            "comparison.reconcile": "comparison",
            "report.generate": "report",
            "report.refresh": "report",
        }.get(action)
        if check_id is None:
            return False
        check = {
            "source": self.projection.source,
            "runtime": self.projection.runtime,
            "comparison": self.projection.comparison,
            "report": self.projection.report,
        }[check_id]
        return check.operation.value == "failed" or check.lifecycle.value in {
            "failed",
            "corrupt",
            "unsupported",
        }

    def _refresh_projection_from_disk(self) -> None:
        try:
            self.context = discover_project_context(
                self.context.project_root,
                cwd=self.context.opened_from,
            )
            assessment = assess_repository(self.context.project_root, require_static=False)
            report_assessment = assess_report(
                self.context.project_root,
                language=self.language,
            )
            self.projection = build_workspace_projection(
                self.context,
                assessment,
                report_assessment=report_assessment,
                session=self.session,
                language=self.language,
            )
        except (OSError, ValueError):
            # Keep the previous projection if a refresh itself cannot read the
            # repository; the preserved activity still explains recovery.
            return

    def _record_activity(self, item: str) -> None:
        self.activity.append(item)
        self.activity = self.activity[-5:]

    def _ledger_items(self) -> list[ListItem]:
        checks = (
            self.projection.source,
            self.projection.runtime,
            self.projection.comparison,
            self.projection.report,
        )
        return [
            ListItem(
                Horizontal(
                    Static(
                        self._status_token(check),
                        markup=False,
                        id=f"ledger-status-{check.id}",
                        classes="status-marker",
                    ),
                    Static(
                        self._row_text(check),
                        markup=False,
                        id=f"ledger-{check.id}",
                        classes="ledger-copy",
                    ),
                ),
                id=f"row-{check.id}",
                classes="selected-row" if check.id == self.selected_id else None,
            )
            for check in checks
        ]

    def _selected_index(self) -> int:
        return ("source", "runtime", "comparison", "report").index(self.selected_id)

    def _row_text(self, check: WorkspaceCheck) -> str:
        label = message(f"workspace.item.{check.id}", self.language)
        primary, secondary = self._state_text(check)
        state = f"{primary} · {secondary}" if secondary else primary
        return f"{label}\n    {state}"

    def _state_text(self, check: WorkspaceCheck) -> tuple[str, str]:
        if self._action_targets_check(self._running_action, check.id):
            return (
                message("workspace.state.running", self.language),
                self._action_label(self._running_action),
            )
        if check.lifecycle.value == "missing":
            secondary = {
                "source": "workspace.state.start_here",
                "runtime": "workspace.state.optional",
                "comparison": "workspace.state.verify_first",
                "report": "workspace.state.report_after_source",
            }.get(check.id)
            return (
                message(f"workspace.state.missing.{check.id}", self.language),
                message(secondary, self.language) if secondary else "",
            )
        elif check.lifecycle.value == "corrupt":
            key = (
                "workspace.state.report_unreadable"
                if check.id == "report"
                else "workspace.state.corrupt"
            )
            return message(key, self.language), message(
                "workspace.state.result_details", self.language
            )
        elif check.lifecycle.value in {"failed", "unsupported"}:
            key = (
                "workspace.state.comparison_failed"
                if check.id == "comparison"
                else "workspace.state.failed"
            )
            return message(key, self.language), message(
                "workspace.state.result_details", self.language
            )
        elif check.outcome is DomainOutcome.DRIFT_DETECTED:
            return (
                message("workspace.state.drift", self.language),
                message("workspace.state.attention", self.language),
            )
        elif check.id == "comparison" and check.outcome is DomainOutcome.MATCHED:
            return (
                message("workspace.state.matched", self.language),
                message("workspace.state.compared_no_differences", self.language),
            )
        elif "language_mismatch" in check.reason_codes:
            return (
                message("workspace.state.language_mismatch", self.language),
                message("workspace.state.report_language_changed", self.language),
            )
        elif check.id == "runtime" and check.lifecycle.value == "valid":
            return (
                message("workspace.state.snapshot", self.language),
                message("workspace.state.snapshot_available", self.language),
            )
        elif check.id == "source":
            if check.freshness is Freshness.STALE:
                return (
                    message("workspace.state.stale", self.language),
                    message("workspace.state.source_changed", self.language),
                )
            if check.freshness in {Freshness.UNCERTAIN, Freshness.UNKNOWN}:
                if "dirty_worktree_provenance_insufficient" in check.reason_codes:
                    return (
                        message("workspace.state.checked", self.language),
                        message("workspace.state.workspace_changed", self.language),
                    )
                return (
                    message("workspace.state.checked", self.language),
                    message("workspace.state.result_may_be_old", self.language),
                )
            return (
                message("workspace.state.checked", self.language),
                message("workspace.state.matches_source", self.language),
            )
        elif check.id == "comparison":
            if check.freshness is Freshness.STALE:
                return (
                    message("workspace.state.stale", self.language),
                    message("workspace.state.comparison_inputs_changed", self.language),
                )
            if check.freshness in {Freshness.UNCERTAIN, Freshness.UNKNOWN}:
                return (
                    message("workspace.state.uncertain", self.language),
                    message("workspace.state.comparison_not_current", self.language),
                )
        elif check.id == "report":
            if check.freshness is Freshness.STALE:
                return (
                    message("workspace.state.stale", self.language),
                    message("workspace.state.results_changed", self.language),
                )
            if check.freshness in {Freshness.UNCERTAIN, Freshness.UNKNOWN}:
                return (
                    message("workspace.state.uncertain", self.language),
                    message("workspace.state.result_may_be_old", self.language),
                )
            if check.lifecycle.value == "valid":
                return (
                    message("workspace.state.generated", self.language),
                    message("workspace.state.report_current", self.language),
                )
        primary = message("workspace.state.valid", self.language)
        try:
            outcome = message(
                f"workspace.outcome.{check.outcome.value}",
                self.language,
            )
        except KeyError:
            outcome = check.outcome.value.replace("_", " ")
        return primary, outcome

    def _status_token(self, check: WorkspaceCheck) -> str:
        if self._action_targets_check(self._running_action, check.id):
            return ">"
        if check.lifecycle.value in {"failed", "corrupt", "unsupported"}:
            return "!"
        if check.lifecycle.value == "missing":
            return "—"
        if check.freshness is Freshness.STALE:
            return "~"
        if "language_mismatch" in check.reason_codes:
            return "~"
        if check.freshness in {Freshness.UNCERTAIN, Freshness.UNKNOWN}:
            return "?"
        return "✓"

    def _human_detail_text(self) -> str:
        check = self._selected_check()
        lines = [
            message(f"workspace.item.{check.id}", self.language),
            self._human_detail_heading(check),
            "",
            message("workspace.detail.explanation", self.language),
            f"· {self._human_detail_explanation(check)}",
        ]
        lines.extend(self._human_detail_fields(check))
        actions = self._context_actions()
        if actions:
            lines.extend(["", message("workspace.detail.next_steps", self.language)])
            lines.extend(f"· {self._action_label(action)}" for action in actions)
        return "\n".join(lines)

    def _human_detail_heading(self, check: WorkspaceCheck) -> str:
        if check.id == "source":
            if check.lifecycle.value == "missing":
                return message("workspace.detail.source.not_checked", self.language)
            if check.lifecycle.value in {"failed", "corrupt", "unsupported"}:
                return message("workspace.detail.source.failed", self.language)
            if check.freshness is Freshness.STALE:
                return message("workspace.detail.source.stale", self.language)
            if check.freshness in {Freshness.UNCERTAIN, Freshness.UNKNOWN}:
                return message("workspace.detail.source.uncertain", self.language)
            return message("workspace.detail.source.checked", self.language)
        if check.id == "runtime":
            if check.lifecycle.value == "missing":
                return message("workspace.detail.mysql.not_verified", self.language)
            if check.lifecycle.value in {"failed", "corrupt", "unsupported"}:
                return message("workspace.detail.mysql.failed", self.language)
            if check.lifecycle.value == "valid":
                return message("workspace.detail.mysql.snapshot", self.language)
            return message("workspace.detail.mysql.unknown", self.language)
        if check.id == "comparison":
            if check.lifecycle.value == "missing":
                return message("workspace.detail.comparison.not_compared", self.language)
            if check.lifecycle.value in {"failed", "corrupt", "unsupported"}:
                return message("workspace.detail.comparison.failed", self.language)
            if check.freshness is Freshness.STALE:
                return message("workspace.detail.comparison.stale", self.language)
            if check.freshness in {Freshness.UNCERTAIN, Freshness.UNKNOWN}:
                return message("workspace.detail.comparison.unknown", self.language)
            if check.outcome is DomainOutcome.DRIFT_DETECTED:
                return message("workspace.detail.comparison.differences", self.language)
            return message("workspace.detail.comparison.no_differences", self.language)
        if check.lifecycle.value == "missing":
            return message("workspace.detail.report.none", self.language)
        if check.freshness is Freshness.STALE or "language_mismatch" in check.reason_codes:
            return message("workspace.detail.report.needs_refresh", self.language)
        if check.lifecycle.value in {"corrupt", "unsupported"} or check.freshness in {
            Freshness.UNKNOWN,
            Freshness.UNCERTAIN,
        }:
            return message("workspace.detail.report.unknown", self.language)
        if check.lifecycle.value == "valid":
            return message("workspace.detail.report.generated", self.language)
        return message("workspace.detail.report.unknown", self.language)

    def _human_detail_explanation(self, check: WorkspaceCheck) -> str:
        if check.id == "source":
            if check.lifecycle.value == "missing":
                return message("workspace.state.start_here", self.language)
            if check.lifecycle.value in {"failed", "corrupt", "unsupported"}:
                return message("workspace.state.result_details", self.language)
            if check.freshness is Freshness.STALE:
                return message("workspace.state.source_changed", self.language)
            if check.freshness in {Freshness.UNCERTAIN, Freshness.UNKNOWN}:
                return message("workspace.state.result_may_be_old", self.language)
            return message("workspace.state.matches_source", self.language)
        if check.id == "runtime":
            if check.lifecycle.value == "missing":
                return message(
                    "workspace.detail.mysql.explanation.not_verified", self.language
                )
            if check.lifecycle.value in {"failed", "corrupt", "unsupported"}:
                return message(
                    "workspace.detail.mysql.explanation.failed", self.language
                )
            return message("workspace.detail.mysql.explanation.snapshot", self.language)
        if check.id == "comparison":
            if check.lifecycle.value == "missing":
                return message("workspace.state.verify_first", self.language)
            if check.lifecycle.value in {"failed", "corrupt", "unsupported"}:
                return message("workspace.state.result_details", self.language)
            if check.freshness is Freshness.STALE:
                return message(
                    "workspace.state.comparison_inputs_changed", self.language
                )
            if check.freshness in {Freshness.UNCERTAIN, Freshness.UNKNOWN}:
                return message(
                    "workspace.detail.comparison.unknown", self.language
                )
            if check.outcome is DomainOutcome.DRIFT_DETECTED:
                return message(
                    "workspace.detail.comparison.differences", self.language
                )
            return message(
                "workspace.detail.comparison.no_differences", self.language
            )
        if check.lifecycle.value == "missing":
            return message("workspace.detail.report.not_ready", self.language)
        if check.freshness is Freshness.STALE:
            return message("workspace.state.results_changed", self.language)
        if "language_mismatch" in check.reason_codes:
            return message("workspace.state.report_language_changed", self.language)
        if check.lifecycle.value in {"corrupt", "unsupported"} or check.freshness in {
            Freshness.UNKNOWN,
            Freshness.UNCERTAIN,
        }:
            return message("workspace.detail.report.unknown", self.language)
        return message("workspace.detail.report.ready", self.language)

    def _human_detail_fields(self, check: WorkspaceCheck) -> list[str]:
        lines: list[str] = []
        if check.id == "source":
            if check.observed_at is not None:
                lines.append(
                    message(
                        "workspace.detail.checked_at",
                        self.language,
                        value=_format_detail_time(check.observed_at),
                    )
                )
            lines.append(
                message(
                    "workspace.detail.source.coverage",
                    self.language,
                    value=message(
                        "workspace.detail.source.coverage.default", self.language
                    ),
                )
            )
            lines.append(message("workspace.detail.source.evidence", self.language))
        elif check.id == "runtime":
            if check.lifecycle.value == "valid" and check.observed_at is not None:
                lines.append(
                    message(
                        "workspace.detail.snapshot_at",
                        self.language,
                        value=_format_detail_time(check.observed_at),
                    )
                )
            lines.append(message("workspace.detail.mysql.detail", self.language))
        elif check.id == "comparison":
            if check.outcome is DomainOutcome.DRIFT_DETECTED:
                finding = message(
                    "workspace.detail.comparison.differences", self.language
                )
            elif check.outcome is DomainOutcome.MATCHED:
                finding = message(
                    "workspace.detail.comparison.no_differences", self.language
                )
            else:
                finding = message("workspace.detail.no_summary", self.language)
            lines.append(
                message(
                    "workspace.detail.comparison.finding",
                    self.language,
                    value=finding,
                )
            )
        else:
            if check.provenance_summary:
                lines.append(
                    message(
                        "workspace.detail.report.language",
                        self.language,
                        value=self._report_language_text(check.provenance_summary[0]),
                    )
                )
            else:
                lines.append(message("workspace.detail.report.no_language", self.language))
            if check.observed_at is not None:
                lines.append(
                    message(
                        "workspace.detail.report.generated_at",
                        self.language,
                        value=_format_detail_time(check.observed_at),
                    )
                )
            if check.lifecycle.value != "missing":
                lines.append(
                    message(
                        "workspace.detail.report.path",
                        self.language,
                        value=str(check.artifact_path),
                    )
                )
        return lines

    def _technical_detail_text(self) -> str:
        check = self._selected_check()
        reason_codes = ", ".join(check.reason_codes) or "—"
        provenance = ", ".join(check.provenance_summary) or "—"
        observed = (
            check.observed_at.isoformat(timespec="seconds")
            if check.observed_at is not None
            else "—"
        )
        lines = [
            message(
                "workspace.detail.lifecycle",
                self.language,
                value=check.lifecycle.value,
            ),
            message(
                "workspace.detail.freshness",
                self.language,
                value=check.freshness.value,
            ),
            message(
                "workspace.detail.operation_raw",
                self.language,
                value=check.operation.value,
            ),
            message(
                "workspace.detail.outcome",
                self.language,
                value=check.outcome.value,
            ),
            message("workspace.detail.reason_codes", self.language, value=reason_codes),
            message(
                "workspace.detail.provenance_raw", self.language, value=provenance
            ),
            message("workspace.detail.observed", self.language, value=observed),
            message(
                "workspace.detail.artifact_path",
                self.language,
                value=str(check.artifact_path),
            ),
            message(
                "workspace.detail.hash",
                self.language,
                value=self._artifact_hash(check.artifact_path),
            ),
        ]
        if self._operation_error_type and self._action_targets_check(
            self._failed_action, check.id
        ):
            lines.append(
                message(
                    "workspace.detail.technical_code",
                    self.language,
                    value=self._operation_error_type,
                )
            )
        return "\n".join(lines)

    def _report_language_text(self, value: str) -> str:
        key = {
            "en": "workspace.language.en",
            "zh-CN": "workspace.language.zh_cn",
        }.get(value)
        label = message(key, self.language) if key else message(
            "workspace.language.unknown", self.language
        )
        return f"{label} · {value}"

    @staticmethod
    def _artifact_hash(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return "unavailable"

    def _workspace_term(self, value: str) -> str:
        try:
            return message(f"workspace.term.{value}", self.language)
        except KeyError:
            return value

    def _reason_text(self, value: str) -> str:
        try:
            return message(f"workspace.reason.{value}", self.language)
        except KeyError:
            return message("workspace.detail.technical_code", self.language, value=value)

    def _operation_label(self, check: WorkspaceCheck) -> str:
        if self._action_targets_check(self._running_action, check.id):
            return message("workspace.operation.running_label", self.language)
        key = {
            "idle": "workspace.operation.idle",
            "running": "workspace.operation.running_label",
            "cancel_requested": "workspace.operation.cancel_requested",
            "succeeded": "workspace.operation.succeeded",
            "failed": "workspace.operation.failed",
            "partial": "workspace.operation.partial",
        }.get(check.operation.value)
        return message(key, self.language) if key else check.operation.value

    @staticmethod
    def _action_targets_check(action: str | None, check_id: str) -> bool:
        return (
            action in {"source.inspect", "source.scan_only"} and check_id == "source"
        ) or (
            action in {"report.generate", "report.refresh", "report.open"}
            and check_id == "report"
        ) or (action == "runtime.verify_mysql" and check_id == "runtime") or (
            action == "comparison.reconcile" and check_id == "comparison"
        )

    def _selected_check(self) -> WorkspaceCheck:
        return {
            "source": self.projection.source,
            "runtime": self.projection.runtime,
            "comparison": self.projection.comparison,
            "report": self.projection.report,
        }[self.selected_id]

    def _context_actions(self) -> list[str]:
        available = set(self._selected_check().available_actions)
        preferred = (
            "source.inspect",
            "runtime.verify_mysql",
            "view.finding",
            "comparison.reconcile",
            "report.generate",
            "report.refresh",
            "report.open",
            "view.source",
            "view.runtime",
            "view.comparison",
            "help.open",
        )
        return [action for action in preferred if action in available][:2]

    def _primary_button_action(self) -> str | None:
        actions = self._context_actions()
        return actions[0] if actions else self.projection.primary_action

    def _secondary_button_action(self) -> str | None:
        actions = self._context_actions()
        if len(actions) > 1:
            return actions[1]
        if self.selected_id == "source" and actions:
            return self.projection.secondary_action
        return None

    def _activity_text(self) -> str:
        items = self.activity[-4:]
        if self._live_activity:
            items = [*items, self._live_activity]
        if not items:
            return message("workspace.detail.empty_activity", self.language)
        return "\n".join(f"· {item}" for item in items[-5:])

    def _activity_visible(self) -> bool:
        return bool(self.activity or self._live_activity)

    def _show_onboarding(self) -> bool:
        return self.projection.source.lifecycle.value == "missing"

    def _footer_status_text(self) -> str:
        git = self.context.git
        branch = git.branch or ("local" if not git.repository else "detached")
        return message(
            "workspace.footer.status",
            self.language,
            branch=branch,
            source=self._status_token(self.projection.source),
            runtime=self._status_token(self.projection.runtime),
            comparison=self._status_token(self.projection.comparison),
            report=self._status_token(self.projection.report),
        )

    def _language_label(self) -> str:
        if self.has_class("very-narrow"):
            return "中文" if self.language == "zh-CN" else "en"
        key = (
            "workspace.footer.language.zh_cn"
            if self.language == "zh-CN"
            else "workspace.footer.language.en"
        )
        return message(key, self.language)

    def _show_live_activity(self) -> None:
        self._live_delay_timer = None
        if self._running_action is None:
            return
        self._live_activity = message(
            "workspace.activity.running",
            self.language,
            label=self._action_label(self._running_action),
            elapsed=_format_elapsed(self._elapsed_seconds()),
        )
        self._live_timer = self.set_interval(0.2, self._refresh_live_activity)
        self._refresh_labels()

    def _refresh_live_activity(self) -> None:
        if self._running_action is None:
            self._stop_live_timers()
            return
        self._live_activity = message(
            "workspace.activity.running",
            self.language,
            label=self._action_label(self._running_action),
            elapsed=_format_elapsed(self._elapsed_seconds()),
        )
        self._refresh_labels()

    def _elapsed_seconds(self) -> float:
        if self._running_since is None:
            return 0.0
        return max(0.0, time.monotonic() - self._running_since)

    def _stop_live_timers(self) -> None:
        for timer_name in ("_live_delay_timer", "_live_timer"):
            timer = getattr(self, timer_name)
            if timer is not None:
                timer.stop()
                setattr(self, timer_name, None)

    def _header_text(self) -> Text:
        git = self.context.git
        if git.repository:
            branch = git.branch or "detached"
            commit = git.short_commit or "unknown"
            state = message(
                "workspace.header.dirty" if git.dirty else "workspace.header.clean"
                if git.dirty is False
                else "workspace.header.unknown",
                self.language,
            )
            git_line = f"{branch} · {commit} · {state}"
        else:
            git_line = message("workspace.header.no_git", self.language)
        header = Text()
        header.append("RepoEvidence\n", style="bold")
        if self.context.repository_name != "RepoEvidence":
            header.append(f"{self.context.repository_name}\n", style="bold")
        header.append(f"{git_line}\n")
        if not self.has_class("narrow"):
            root = _truncate_path(self.context.project_root, limit=56)
            opened_from = _truncate_path(self.context.opened_from, limit=56)
            header.append(
                f"{message('workspace.header.root', self.language)}: {root}",
                style="dim",
            )
            if self._paths_differ():
                header.append(
                    f"\n{message('workspace.header.opened_from', self.language)}: {opened_from}",
                    style="dim",
                )
        return header

    def _paths_differ(self) -> bool:
        return self.context.project_root.resolve() != self.context.opened_from.resolve()

    def _action_label(self, action: str | None) -> str:
        if action is None:
            return ""
        key = {
            "source.inspect": "workspace.action.inspect",
            "source.scan_only": "workspace.action.inspect",
            "runtime.verify_mysql": "workspace.action.verify",
            "comparison.reconcile": "workspace.action.compare",
            "report.generate": "workspace.action.report_generate",
            "report.refresh": "workspace.action.report_refresh",
            "report.open": "workspace.action.report_open",
            "view.source": "workspace.action.view_source",
            "view.runtime": "workspace.action.view_runtime",
            "view.comparison": "workspace.action.view_comparison",
            "view.report": "workspace.action.view_report",
            "view.finding": "workspace.action.view_finding",
            "help.open": "workspace.action.help",
            "settings.open": "workspace.action.settings",
            "app.quit": "workspace.action.quit",
        }.get(action, action)
        return message(key, self.language)

    def _apply_theme_class(self) -> None:
        for class_name in ("theme-light", "theme-dark", "reduced-motion"):
            self.remove_class(class_name)
        theme = self.settings.theme
        if theme == "light":
            self.add_class("theme-light")
        else:
            self.add_class("theme-dark")
        if self.settings.reduced_motion:
            self.add_class("reduced-motion")

    def _save_settings_safely(self) -> None:
        if not self.persist_settings:
            return
        try:
            save_user_settings(self.settings)
        except OSError:
            # Preferences must never prevent a workspace session from running.
            pass


def _truncate_path(path: Path, limit: int = 68) -> str:
    value = str(path)
    if len(value) <= limit:
        return value
    return f"…{value[-(limit - 1):]}"


def _inspect_succeeded(result: WorkspaceOperationResult | None) -> bool:
    if result is None:
        return False
    value = result.value
    summary = getattr(value, "summary", None)
    return summary is not None and not bool(getattr(summary, "errors", ()))


def _event_elapsed(event: OperationEvent, fallback: float) -> float:
    value = event.safe_metadata.get("elapsed_ms")
    if isinstance(value, (int, float)):
        return max(0.0, float(value) / 1000.0)
    return fallback


def _format_detail_time(value: datetime) -> str:
    timestamp = value
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def _format_elapsed(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}m {remainder:02d}s"


def run_workspace(
    path: str | Path | None = None,
    *,
    language: str | None = None,
    settings: UserSettings | None = None,
) -> int:
    """Discover, project, and run a workspace without startup operations."""

    loaded = load_user_settings() if settings is None else None
    effective_settings = settings or loaded.settings
    effective_language = resolve_language(
        language,
        user_language=effective_settings.language,
    )
    context = discover_project_context(path)
    assessment = assess_repository(context.project_root, require_static=False)
    report_assessment = assess_report(context.project_root, language=effective_language)
    projection = build_workspace_projection(
        context,
        assessment,
        report_assessment=report_assessment,
        language=effective_language,
    )
    RepoEvidenceApp(
        context,
        projection,
        language=effective_language,
        settings=effective_settings,
        persist_settings=True,
    ).run()
    return 0
