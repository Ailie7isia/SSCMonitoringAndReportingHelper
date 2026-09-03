"""Windows dashboard for SecurityScorecard portfolio operations."""

from __future__ import annotations

import csv
import logging
import os
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from config import CONFIG_PATH, REPORTS_DIR, load_config, validate_ssc_config
from constants import OPTION_LABELS, OPTION_VENDORS
from models import Company
from Services.portfolio import (
    apply_plan,
    companies_from_payload,
    compute_plan,
    target_domains,
)
from Services.reports import download_reports
from Services.scores import (
    SCORE_HISTORY_PATH,
    append_score_history,
    current_month_history_status,
    grade_statistics,
    score_change_over_past_month,
    score_trends_from_history,
)
from ssc_client import ApiRequestError, SecurityScorecardClient
from utils import sanitize_filename

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

BACKGROUND, PANEL, PANEL_ALT = "#101923", "#182532", "#213240"
ACCENT, MUTED = "#2FBF8F", "#9CB2C2"
GRADE_COLORS = {"A": "#35C98A", "B": "#F1BE4D", "C": "#F48F4A", "D": "#EE5D69", "F": "#C93546"}


class QueueLogHandler(logging.Handler):
    def __init__(self, destination: "queue.Queue[str]") -> None:
        super().__init__()
        self.destination = destination

    def emit(self, record: logging.LogRecord) -> None:
        self.destination.put(self.format(record))


class Dashboard(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SSC Monitoring Helper")
        self.geometry("1240x790")
        self.minsize(1050, 680)
        self.configure(fg_color=BACKGROUND)
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.busy = False
        self.current_companies: list[Company] = []
        self._build_layout()
        self._build_loading_overlay()
        self.after(150, self._poll_log_queue)
        self.after(350, self.refresh_dashboard)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        sidebar = ctk.CTkFrame(self, width=255, corner_radius=0, fg_color="#14212D")
        sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sidebar.grid_propagate(False)
        ctk.CTkLabel(sidebar, text="SSC", font=("Segoe UI", 29, "bold"), text_color=ACCENT).pack(anchor="w", padx=27, pady=(31, 0))
        ctk.CTkLabel(sidebar, text="MONITORING HELPER", font=("Segoe UI", 14, "bold"), text_color=MUTED).pack(anchor="w", padx=29, pady=(0, 37))
        self.operation_buttons: list[ctk.CTkButton] = []
        self._side_button(sidebar, "↻   Refresh portfolio", self.refresh_dashboard)
        self._side_button(sidebar, "◈   Run portfolio cycle", self.open_cycle_dialog)
        self._side_button(sidebar, "↓   Download detailed reports", self.start_detailed_reports_download)
        self._side_button(sidebar, "↓   Download issue reports", self.start_issue_reports_download)
        self._side_button(sidebar, "▣   Open reports folder", self.open_reports_folder)
        self._side_button(sidebar, "↑   Update score history", self.start_score_export)
        self.history_status = ctk.CTkLabel(
            sidebar,
            text="Checking score history…",
            justify="left",
            font=("Segoe UI", 14),
            text_color=MUTED,
        )
        self.history_status.pack(anchor="w", padx=29, pady=(6, 0))
        self._update_history_status()
        self._side_button(sidebar, "↗   View score trends", self.open_score_trends)
        ctk.CTkLabel(sidebar, text="SECURE WORKFLOW", font=("Segoe UI", 14, "bold"), text_color=MUTED).pack(anchor="w", padx=29, pady=(35, 8))
        ctk.CTkLabel(sidebar, text="Portfolio changes always\nrequire confirmation.", justify="left", font=("Segoe UI", 14), text_color="#C8D5DD").pack(anchor="w", padx=29)
        self.sidebar_status = ctk.CTkLabel(sidebar, text="●  Ready", font=("Segoe UI", 14, "bold"), text_color=ACCENT)
        self.sidebar_status.pack(side="bottom", anchor="w", padx=29, pady=28)

        self.dashboard_header = ctk.CTkFrame(self, height=112, corner_radius=0, fg_color=BACKGROUND)
        self.dashboard_header.grid(row=0, column=1, sticky="new", padx=35)
        self.dashboard_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.dashboard_header, text="SSC Monitoring Helper", font=("Segoe UI", 29, "bold")).grid(row=0, column=0, sticky="sw", pady=(25, 0))
        self.last_updated = ctk.CTkLabel(self.dashboard_header, text="Loading portfolio data…", font=("Segoe UI", 14), text_color=MUTED)
        self.last_updated.grid(row=1, column=0, sticky="nw", pady=(2, 0))
        self.refresh_button = ctk.CTkButton(self.dashboard_header, text="Refresh now", width=125, height=34, command=self.refresh_dashboard, fg_color=PANEL_ALT, hover_color="#2C4354", font=("Segoe UI", 14))
        self.refresh_button.grid(row=0, column=1, rowspan=2, sticky="e")

        self.dashboard_body = ctk.CTkScrollableFrame(self, fg_color=BACKGROUND, corner_radius=0)
        self.dashboard_body.grid(row=1, column=1, sticky="nsew", padx=(31, 23), pady=(0, 20))
        body = self.dashboard_body
        body.grid_columnconfigure((0, 1, 2), weight=1)
        self.metric_values: dict[str, ctk.CTkLabel] = {}
        self.metric_subtitles: dict[str, ctk.CTkLabel] = {}
        for index, (key, title, value, subtitle, color) in enumerate((
            ("companies", "Active domains", "—", "Current portfolio", ACCENT),
            ("kalbe", "Kalbe.co.id score", "—", "No 30-day comparison yet", "#6BAFFF"),
            ("attention", "Needs attention", "—", "Grade C or below", "#F2B84B"),
        )):
            card = self._metric_card(body, title, value, subtitle, color)
            card.grid(row=0, column=index, sticky="ew", padx=7, pady=(5, 14))
            self.metric_values[key] = card.value_label  # type: ignore[attr-defined]
            self.metric_subtitles[key] = card.subtitle_label  # type: ignore[attr-defined]

        domains = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=14)
        domains.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=7, pady=7)
        domains.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(domains, text="Currently active domains", font=("Segoe UI", 17, "bold")).grid(row=0, column=0, sticky="w", padx=20, pady=(17, 1))
        ctk.CTkLabel(domains, text="Live scores are color-coded by company grade", font=("Segoe UI", 14), text_color=MUTED).grid(row=1, column=0, sticky="w", padx=20)
        self.copy_domains_button = ctk.CTkButton(
            domains,
            text="Copy all",
            width=98,
            height=30,
            command=self._copy_active_domains,
            fg_color=PANEL_ALT,
            hover_color="#2C4354",
            font=("Segoe UI", 13, "bold"),
            state="disabled",
        )
        self.copy_domains_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=20, pady=(12, 0))
        self.domain_rows = ctk.CTkScrollableFrame(domains, height=245, fg_color="#0E1821", corner_radius=9)
        self.domain_rows.grid(row=2, column=0, sticky="ew", padx=20, pady=(12, 20))
        self.domain_rows.grid_columnconfigure(0, weight=1)
        self._render_domains([])

        actions = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=14)
        actions.grid(row=1, column=2, sticky="nsew", padx=7, pady=7)
        ctk.CTkLabel(actions, text="Recommended next step", font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=20, pady=(18, 5))
        self.recommendation = ctk.CTkLabel(actions, text="Load the portfolio to see a tailored recommendation.", justify="left", wraplength=240, font=("Segoe UI", 14), text_color="#D5E0E6")
        self.recommendation.pack(anchor="w", padx=20, pady=(0, 17))
        self.action_button = ctk.CTkButton(actions, text="Run portfolio cycle", command=self.open_cycle_dialog, fg_color=ACCENT, hover_color="#249E74", font=("Segoe UI", 14))
        self.action_button.pack(fill="x", padx=20, pady=(0, 19))

        activity = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=14)
        activity.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=7, pady=(15, 8))
        activity.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(activity, text="Activity", font=("Segoe UI", 17, "bold")).grid(row=0, column=0, sticky="w", padx=20, pady=(17, 7))
        self.activity = ctk.CTkTextbox(activity, height=188, font=("Cascadia Mono", 14), fg_color="#0E1821", border_width=0)
        self.activity.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.activity.tag_config("failure", foreground="#FF6B73")
        self.activity.insert("end", "Monitoring Helper started. Loading current portfolio…\n")
        self.activity.configure(state="disabled")

    def _build_loading_overlay(self) -> None:
        """A modal, full-window state keeps long API operations unambiguous."""
        self.loading_overlay = ctk.CTkFrame(self, fg_color="#0B141D", corner_radius=0)
        panel = ctk.CTkFrame(self.loading_overlay, width=520, height=250, fg_color=PANEL, corner_radius=18)
        panel.place(relx=0.5, rely=0.5, anchor="center")
        panel.pack_propagate(False)
        ctk.CTkLabel(panel, text="SECURITYSCORECARD", font=("Segoe UI", 14, "bold"), text_color=ACCENT).pack(pady=(45, 8))
        self.loading_title = ctk.CTkLabel(panel, text="Loading portfolio", font=("Segoe UI", 25, "bold"))
        self.loading_title.pack(pady=(0, 8))
        ctk.CTkLabel(panel, text="Please wait — Monitoring Helper will update automatically.", font=("Segoe UI", 14), text_color=MUTED).pack(pady=(0, 25))
        self.loading_bar = ctk.CTkProgressBar(panel, width=390, height=14, mode="indeterminate", progress_color=ACCENT)
        self.loading_bar.pack()

    def _side_button(self, parent: ctk.CTkFrame, text: str, command: Callable[[], None]) -> None:
        button = ctk.CTkButton(parent, text=text, command=command, anchor="w", height=43, corner_radius=8, fg_color="transparent", hover_color=PANEL_ALT, font=("Segoe UI", 14))
        button.pack(fill="x", padx=17, pady=(3, 0))
        self.operation_buttons.append(button)

    @staticmethod
    def _metric_card(parent: ctk.CTkFrame, title: str, value: str, subtitle: str, color: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=14)
        ctk.CTkLabel(card, text=title.upper(), font=("Segoe UI", 14, "bold"), text_color=MUTED).pack(anchor="w", padx=19, pady=(16, 0))
        label = ctk.CTkLabel(card, text=value, font=("Segoe UI", 30, "bold"), text_color=color)
        label.pack(anchor="w", padx=19, pady=(1, 0))
        subtitle_label = ctk.CTkLabel(card, text=subtitle, font=("Segoe UI", 14), text_color=MUTED)
        subtitle_label.pack(anchor="w", padx=19, pady=(0, 15))
        card.value_label = label  # type: ignore[attr-defined]
        card.subtitle_label = subtitle_label  # type: ignore[attr-defined]
        return card

    def _set_busy(
        self,
        busy: bool,
        status: str = "Ready",
        *,
        show_loading_overlay: bool = True,
    ) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in self.operation_buttons:
            button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.action_button.configure(state=state)
        self.sidebar_status.configure(text=f"{'◌' if busy else '●'}  {status}", text_color="#F2B84B" if busy else ACCENT)
        if busy and show_loading_overlay:
            self.loading_title.configure(text=status)
            self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.loading_bar.start()
        else:
            self.loading_bar.stop()
            self.loading_overlay.place_forget()

    def _log(self, text: str) -> None:
        self.log_queue.put(text)

    def _update_history_status(self) -> tuple[datetime | None, int]:
        """Show the most recent score-history update made this month."""
        saved_at, records = current_month_history_status()
        if saved_at is None:
            self.history_status.configure(
                text="○  No score history saved\nthis month yet",
                text_color="#F2B84B",
            )
        else:
            self.history_status.configure(
                text=f"✓  Latest history update\n{saved_at:%d %b %Y, %H:%M} • {records} records this month",
                text_color=ACCENT,
            )
        return saved_at, records

    def _poll_log_queue(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.activity.configure(state="normal")
                message = line.rstrip() + "\n"
                is_failure = message.lstrip().startswith("✗") or " failed" in message.lower()
                self.activity.insert("end", message, "failure" if is_failure else None)
                self.activity.see("end")
                self.activity.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._poll_log_queue)

    @staticmethod
    def _client() -> tuple[SecurityScorecardClient, str]:
        config = load_config(CONFIG_PATH)
        api_key, portfolio_id = validate_ssc_config(config)
        return SecurityScorecardClient(api_key), portfolio_id

    def _run(
        self,
        label: str,
        task: Callable[[], None],
        *,
        show_loading_overlay: bool = True,
    ) -> None:
        if self.busy:
            return
        self._set_busy(True, label, show_loading_overlay=show_loading_overlay)
        self._log(f"› {label}")
        def worker() -> None:
            try:
                task()
            except ApiRequestError as exc:
                self._log(f"✗ SecurityScorecard request failed: {exc}")
            except (FileNotFoundError, ValueError) as exc:
                self._log(f"✗ Configuration issue: {exc}")
            except Exception as exc:
                self._log(f"✗ Operation failed: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))
        threading.Thread(target=worker, daemon=True).start()

    def refresh_dashboard(self) -> None:
        def load() -> None:
            client, portfolio_id = self._client()
            companies = companies_from_payload(client.fetch_portfolio_companies(portfolio_id))
            enriched: list[Company] = []
            for company in companies:
                details = client.get_company(company.domain)
                enriched.append(Company(company.domain, company.name, str(details.get("grade") or "").upper(), details.get("score")))
            kalbe = next((company for company in enriched if company.domain.lower() == "kalbe.co.id"), None)
            kalbe_trend = score_change_over_past_month(kalbe.domain, kalbe.score) if kalbe else None
            self.after(0, lambda: self._update_dashboard(enriched, kalbe_trend))
            self._log(f"✓ Portfolio refreshed: {len(enriched)} companies loaded.")
        self._run("Refreshing portfolio", load)

    def _update_dashboard(
        self,
        companies: list[Company],
        kalbe_trend: float | None,
    ) -> None:
        self.current_companies = companies
        grades = grade_statistics(companies)
        attention = sum(grades.get(grade, 0) for grade in ("C", "D", "F"))
        kalbe = next((company for company in companies if company.domain.lower() == "kalbe.co.id"), None)
        self.metric_values["companies"].configure(text=str(len(companies)))
        if kalbe and isinstance(kalbe.score, (int, float)):
            grade = kalbe.grade.upper() if kalbe.grade else "Unknown"
            self.metric_values["kalbe"].configure(
                text=f"{kalbe.score:.0f}",
                text_color=GRADE_COLORS.get(grade, MUTED),
            )
            self._set_kalbe_trend(kalbe_trend)
        else:
            self.metric_values["kalbe"].configure(text="—", text_color=MUTED)
            self.metric_subtitles["kalbe"].configure(text="Kalbe.co.id is not in the active portfolio", text_color=MUTED)
        self.metric_values["attention"].configure(text=str(attention))
        self.last_updated.configure(text=f"Last refreshed {datetime.now().strftime('%d %b %Y, %H:%M')}  •  {len(companies)} domains active")
        self._render_domains(companies)
        if attention:
            self.recommendation.configure(text=f"{attention} monitored compan{'y needs' if attention == 1 else 'ies need'} attention. Export the score data to support follow-up.")
            self.action_button.configure(text="Update score history", command=self.start_score_export)
        else:
            self.recommendation.configure(text="No C, D, or F grades currently detected. Review the next portfolio cycle when scheduled.")
            self.action_button.configure(text="Run portfolio cycle", command=self.open_cycle_dialog)

    def _set_kalbe_trend(self, trend: float | None) -> None:
        if trend is None:
            self.metric_subtitles["kalbe"].configure(
                text="No 30-day comparison yet",
                text_color=MUTED,
            )
            return
        amount = f"{abs(trend):.0f}"
        if trend > 0:
            text, color = f"↑ +{amount} vs. 30 days ago", ACCENT
        elif trend < 0:
            text, color = f"↓ −{amount} vs. 30 days ago", "#EE5D69"
        else:
            text, color = "→ No change vs. 30 days ago", MUTED
        self.metric_subtitles["kalbe"].configure(text=text, text_color=color)

    def _render_domains(self, companies: list[Company]) -> None:
        for widget in self.domain_rows.winfo_children():
            widget.destroy()
        if not companies:
            self.copy_domains_button.configure(state="disabled")
            ctk.CTkLabel(self.domain_rows, text="No active domains loaded yet.", font=("Segoe UI", 14), text_color=MUTED).grid(row=0, column=0, sticky="w", padx=12, pady=12)
            return
        self.copy_domains_button.configure(state="normal")
        for row, company in enumerate(sorted(companies, key=lambda item: item.domain.lower())):
            grade = company.grade.upper() if company.grade else "Unknown"
            color = GRADE_COLORS.get(grade, "#718899")
            line = ctk.CTkFrame(self.domain_rows, fg_color="transparent")
            line.grid(row=row, column=0, sticky="ew", padx=5, pady=2)
            line.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(
                line,
                text=company.domain,
                anchor="w",
                command=lambda selected=company: self.open_domain_details(selected),
                fg_color="transparent",
                hover_color=PANEL_ALT,
                font=("Segoe UI", 14),
            ).grid(row=0, column=0, sticky="ew", padx=(3, 12), pady=2)
            score = "—" if company.score is None else str(company.score)
            ctk.CTkLabel(line, text=score, width=48, corner_radius=7, fg_color=color, text_color="#10202A", font=("Segoe UI", 14, "bold")).grid(row=0, column=1, padx=(0, 7), pady=4)
            ctk.CTkLabel(line, text=grade, width=58, text_color=color, font=("Segoe UI", 14, "bold")).grid(row=0, column=2, padx=(0, 7), pady=4)

    def _copy_active_domains(self) -> None:
        """Copy every currently active domain and its latest score details."""
        rows = []
        for company in sorted(self.current_companies, key=lambda item: item.domain.lower()):
            grade = company.grade.upper() if company.grade else "Unknown"
            score = "—" if company.score is None else str(company.score)
            rows.append(f"{company.domain}\t{score}\t{grade}")
        if rows:
            self.clipboard_clear()
            self.clipboard_append("\n".join(rows))
            self._log(f"✓ Copied {len(rows)} active domains to the clipboard.")

    def open_cycle_dialog(self) -> None:
        if self.busy:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Run portfolio cycle")
        dialog.geometry("470x610")
        dialog.resizable(False, False)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="Choose a portfolio cycle", font=("Segoe UI", 22, "bold")).pack(anchor="w", padx=28, pady=(28, 3))
        ctk.CTkLabel(dialog, text="The planned additions and removals will be shown before any changes are made.", justify="left", wraplength=390, font=("Segoe UI", 14), text_color=MUTED).pack(anchor="w", padx=28, pady=(0, 18))
        cycle_options = sorted(OPTION_VENDORS)
        selected = ctk.IntVar(value=cycle_options[0])
        for option in cycle_options:
            cycle_name = OPTION_LABELS.get(option, f"Cycle {option}")
            ctk.CTkRadioButton(
                dialog,
                text=f"Cycle {option} — {cycle_name}",
                variable=selected,
                value=option,
                font=("Segoe UI", 14),
            ).pack(anchor="w", padx=31, pady=6)
        def continue_cycle() -> None:
            dialog.destroy()
            self._run_cycle(selected.get())
        ctk.CTkButton(dialog, text="Review and continue", command=continue_cycle, height=40, fg_color=ACCENT, hover_color="#249E74", font=("Segoe UI", 14)).pack(fill="x", padx=28, pady=27)

    def _run_cycle(self, option: int) -> None:
        def cycle() -> None:
            client, portfolio_id = self._client()
            plan = compute_plan(companies_from_payload(client.fetch_portfolio_companies(portfolio_id)), target_domains(option))
            summary = self._plan_text(option, plan.to_add, plan.to_remove)
            if not self._ask_confirmation("Confirm portfolio changes", summary + "\n\nApply these changes?"):
                self._log("• Portfolio cycle cancelled; no changes were made.")
                return
            report = apply_plan(client, portfolio_id, plan)
            self._log(f"✓ Portfolio cycle complete: {len(report.added_ok)} added, {len(report.removed_ok)} removed, {len(report.added_failed) + len(report.removed_failed)} failed.")
            # Let the current task release the UI first, then reload the
            # management metrics from the updated portfolio.
            self.after(0, lambda: self.after(100, self.refresh_dashboard))
        self._run(f"Reviewing cycle {option}", cycle)

    @staticmethod
    def _plan_text(option: int, to_add: list[str], to_remove: list[str]) -> str:
        additions = "\n".join(f"  + {domain}" for domain in to_add) or "  None"
        removals = "\n".join(f"  − {domain}" for domain in to_remove) or "  None"
        return f"Cycle {option} portfolio plan\n\nAdd ({len(to_add)}):\n{additions}\n\nRemove ({len(to_remove)}):\n{removals}"

    def _ask_confirmation(self, title: str, message: str) -> bool:
        completed = threading.Event()
        answer: dict[str, bool] = {"value": False}

        def ask() -> None:
            # A native confirmation dialog should be the only modal surface the
            # operator sees. Hide the loading overlay until it is answered.
            self.loading_bar.stop()
            self.loading_overlay.place_forget()
            answer["value"] = messagebox.askyesno(title, message, parent=self)
            if answer["value"] and self.busy:
                self.loading_title.configure(text="Applying portfolio changes")
                self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
                self.loading_bar.start()
            completed.set()

        self.after(0, ask)
        completed.wait()
        return answer["value"]

    def start_detailed_reports_download(self) -> None:
        self._start_reports_download("detailed_report", "Detailed PDF reports")

    def start_issue_reports_download(self) -> None:
        self._start_reports_download("issue_report", "Issues CSV reports")

    def _start_reports_download(self, report_type: str, report_label: str) -> None:
        def download() -> None:
            client, portfolio_id = self._client()
            companies = companies_from_payload(client.fetch_portfolio_companies(portfolio_id))
            if not companies:
                self._log("• Portfolio is empty; no reports were downloaded.")
                return
            output_dir = REPORTS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d")
            saved = download_reports(client, companies, output_dir, (report_type,))
            self._log(f"✓ Downloaded {len(saved)} of {len(companies)} {report_label} to {output_dir}.")
        # Report generation can take a while. The service logs each request,
        # wait cycle, and saved file, so keep the Activity panel exposed.
        self._run(
            f"Generating and downloading {report_label.lower()}",
            download,
            show_loading_overlay=False,
        )

    def open_reports_folder(self) -> None:
        """Open the local report archive in Windows Explorer."""
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(REPORTS_DIR))
        except OSError as exc:
            self._log(f"✗ Could not open the reports folder: {exc}")

    def _latest_issue_report(self, company: Company) -> Path | None:
        """Find the newest downloaded SecurityScorecard Issues CSV for a domain."""
        safe_name = sanitize_filename(company.name)
        marker = f" - {safe_name} - Issue Report - "
        dated_folders = sorted(
            (folder for folder in REPORTS_DIR.iterdir() if folder.is_dir()),
            key=lambda folder: folder.name,
            reverse=True,
        ) if REPORTS_DIR.exists() else []
        for folder in dated_folders:
            matches = sorted(
                (path for path in (folder / "issues").glob("*.csv") if marker in path.name),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if matches:
                return matches[0]
        return None

    def open_domain_details(self, company: Company) -> None:
        """Display SecurityScorecard's saved findings and recommendations."""
        issue_report = self._latest_issue_report(company)
        if issue_report is None:
            self._log(f"• No downloaded Issues report is available for {company.domain}. Generate reports first.")
            return
        try:
            with open(issue_report, "r", encoding="utf-8-sig", newline="") as file:
                issues = list(csv.DictReader(file))
        except (OSError, csv.Error) as exc:
            self._log(f"✗ Could not read the Issues report for {company.domain}: {exc}")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"{company.domain} — SecurityScorecard issues")
        dialog.geometry("930x690")
        dialog.minsize(720, 500)
        dialog.configure(fg_color=BACKGROUND)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(dialog, text=company.domain, font=("Segoe UI", 25, "bold")).grid(
            row=0, column=0, sticky="w", padx=28, pady=(27, 0)
        )
        ctk.CTkLabel(
            dialog,
            text=f"{len(issues)} finding(s) from {issue_report.parent.parent.name} • SecurityScorecard Issues report",
            font=("Segoe UI", 14),
            text_color=MUTED,
        ).grid(row=1, column=0, sticky="w", padx=28, pady=(2, 14))
        findings = ctk.CTkScrollableFrame(dialog, fg_color=BACKGROUND, corner_radius=0)
        findings.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 20))
        findings.grid_columnconfigure(0, weight=1)
        if not issues:
            ctk.CTkLabel(findings, text="SecurityScorecard reported no issues in this download.", font=("Segoe UI", 14), text_color=MUTED).grid(
                row=0, column=0, sticky="w", padx=12, pady=16
            )
            return
        for row, issue in enumerate(issues):
            card = ctk.CTkFrame(findings, fg_color=PANEL, corner_radius=12)
            card.grid(row=row, column=0, sticky="ew", padx=8, pady=7)
            card.grid_columnconfigure(0, weight=1)
            severity = (issue.get("ISSUE TYPE SEVERITY") or "Unknown").upper()
            title = issue.get("ISSUE TYPE TITLE") or issue.get("ISSUE TYPE CODE") or "Unnamed issue"
            ctk.CTkLabel(card, text=title, anchor="w", font=("Segoe UI", 15, "bold"), wraplength=700).grid(
                row=0, column=0, sticky="ew", padx=16, pady=(14, 2)
            )
            ctk.CTkLabel(
                card,
                text=f"{severity}  •  {issue.get('FACTOR NAME') or 'Uncategorized'}  •  {issue.get('STATUS') or 'Active'}",
                anchor="w",
                font=("Segoe UI", 14, "bold"),
                text_color=GRADE_COLORS.get("F" if severity in {"HIGH", "CRITICAL"} else "C", "#F2B84B"),
            ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
            target = issue.get("TARGET") or issue.get("HOSTNAME") or issue.get("IP ADDRESSES")
            if target:
                ctk.CTkLabel(card, text=f"Affected: {target}", anchor="w", font=("Segoe UI", 14), text_color=MUTED, wraplength=700).grid(
                    row=2, column=0, sticky="ew", padx=16, pady=(0, 8)
                )
            recommendation = issue.get("ISSUE RECOMMENDATION") or "No recommendation was included in this report."
            ctk.CTkLabel(card, text=f"Recommended solution\n{recommendation}", anchor="w", justify="left", font=("Segoe UI", 14), wraplength=700).grid(
                row=3, column=0, sticky="ew", padx=16, pady=(0, 15)
            )

    def open_score_trends(self) -> None:
        """Load score history without freezing the interface."""
        if not self.current_companies:
            self._log("• Refresh the portfolio before viewing score trends.")
            return
        if self.busy:
            return
        self._set_busy(True, "Loading score trends")

        def load() -> None:
            try:
                history_trends = score_trends_from_history()
                self.after(0, lambda: self._show_score_trends(history_trends))
            except Exception as exc:
                self.after(0, lambda: self._log(f"✗ Could not load score trends: {exc}"))
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=load, daemon=True).start()

    def _show_score_trends(self, history_trends: dict[str, object]) -> None:
        """Display the loaded score history in the trend page."""
        if getattr(self, "trends_page", None) is not None:
            self.trends_page.destroy()
        self.dashboard_header.grid_remove()
        self.dashboard_body.grid_remove()

        self.trends_page = ctk.CTkFrame(self, fg_color=BACKGROUND, corner_radius=0)
        self.trends_page.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(31, 23), pady=(0, 20))
        self.trends_page.grid_columnconfigure(0, weight=1)
        # Keep the descriptive text compact so the results container receives
        # the available vertical space instead of leaving a large gap above it.
        self.trends_page.grid_rowconfigure(3, weight=1, minsize=540)
        ctk.CTkButton(
            self.trends_page, text="←  Back to dashboard", command=self.close_score_trends,
            width=170, height=32, fg_color="transparent", hover_color=PANEL_ALT, anchor="w", font=("Segoe UI", 14),
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(22, 0))
        ctk.CTkLabel(self.trends_page, text="Score trends", font=("Segoe UI", 25, "bold")).grid(
            row=1, column=0, sticky="w", padx=4, pady=(13, 0)
        )
        ctk.CTkLabel(
            self.trends_page,
            text="Scores use the newest saved entry in each calendar month. Missing current-month updates display as —.",
            font=("Segoe UI", 14),
            text_color=MUTED,
        ).grid(row=2, column=0, sticky="nw", padx=4, pady=(2, 14))

        content = ctk.CTkFrame(self.trends_page, height=540, fg_color=PANEL, corner_radius=14)
        content.grid(row=3, column=0, sticky="nsew", padx=4, pady=(0, 8))
        content.grid_columnconfigure(0, weight=1)
        mode = ctk.StringVar(value="All active domains")
        search_text = ctk.StringVar()
        grade_filter = ctk.StringVar(value="All grades")
        switcher = ctk.CTkSegmentedButton(
            content,
            values=["All active domains", "All logged domains"],
            variable=mode,
            width=330,
            font=("Segoe UI", 14),
        )
        switcher.grid(row=0, column=0, sticky="w", padx=20, pady=(18, 8))
        filters = ctk.CTkFrame(content, fg_color="transparent")
        filters.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        filters.grid_columnconfigure(0, weight=1)
        search = ctk.CTkEntry(
            filters,
            textvariable=search_text,
            placeholder_text="Search domains…",
            height=36,
            font=("Segoe UI", 14),
        )
        search.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        grade_menu = ctk.CTkOptionMenu(
            filters,
            variable=grade_filter,
            values=["All grades", "A (90–100)", "B (80–89)", "C (70–79)", "D (60–69)", "F (0–59)", "No score"],
            height=36,
            font=("Segoe UI", 14),
            dropdown_font=("Segoe UI", 14),
        )
        grade_menu.grid(row=0, column=1, sticky="e")
        table = ctk.CTkScrollableFrame(content, fg_color="#0E1821", corner_radius=9)
        table.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 20))
        content.grid_rowconfigure(2, weight=1)
        table.grid_columnconfigure(0, weight=1)

        def delta(value: float | None) -> tuple[str, str]:
            if value is None:
                return "—", MUTED
            if value > 0:
                return f"↑ +{value:.0f}", ACCENT
            if value < 0:
                return f"↓ −{abs(value):.0f}", "#EE5D69"
            return "→ 0", MUTED

        def score_grade(score: float | None) -> str:
            if score is None:
                return "No score"
            if score >= 90:
                return "A"
            if score >= 80:
                return "B"
            if score >= 70:
                return "C"
            if score >= 60:
                return "D"
            return "F"

        def render(_selection: str = "") -> None:
            for widget in table.winfo_children():
                widget.destroy()
            headers = (("Domain", "w"), ("This month score", "e"), ("Last month score", "e"), ("MoM", "e"), ("YoY", "e"))
            for column, (label, anchor) in enumerate(headers):
                table.grid_columnconfigure(column, weight=1 if column == 0 else 0)
                ctk.CTkLabel(
                    table,
                    text=label.upper(),
                    anchor=anchor,
                    font=("Segoe UI", 16 if label == "MoM" else 14, "bold"),
                    text_color=ACCENT if label == "MoM" else MUTED,
                ).grid(
                    row=0, column=column, sticky="ew", padx=12, pady=(10, 7)
                )
            if mode.get() == "All active domains":
                rows = [
                    (company.domain, history_trends.get(company.domain.lower()))
                    for company in self.current_companies
                ]
            else:
                rows = [
                    (domain, trend)
                    for domain, trend in history_trends.items()
                ]
            query = search_text.get().strip().lower()
            selected_grade = "No score" if grade_filter.get() == "No score" else grade_filter.get().split(" ", 1)[0]
            rows = [
                (domain, trend)
                for domain, trend in rows
                if (not query or query in domain.lower())
                and (selected_grade == "All" or score_grade(trend.this_month_score if trend else None) == selected_grade)
            ]
            if not rows:
                ctk.CTkLabel(table, text="No domains match the current search and grade filter.", font=("Segoe UI", 14), text_color=MUTED).grid(
                    row=1, column=0, columnspan=5, sticky="w", padx=12, pady=12
                )
                return
            for row, (domain, trend) in enumerate(sorted(rows, key=lambda item: item[0].lower()), start=1):
                month_text, month_color = delta(trend.month_over_month if trend else None)
                year_text, year_color = delta(trend.year_over_year if trend else None)
                this_month_score = "—" if trend is None or trend.this_month_score is None else f"{trend.this_month_score:.0f}"
                last_month_score = "—" if trend is None or trend.last_month_score is None else f"{trend.last_month_score:.0f}"
                month_background = "#164737" if month_text.startswith("↑") else "#4A2730" if month_text.startswith("↓") else PANEL_ALT
                ctk.CTkLabel(table, text=domain, anchor="w", font=("Segoe UI", 14)).grid(row=row, column=0, sticky="ew", padx=12, pady=6)
                ctk.CTkLabel(table, text=this_month_score, anchor="e", font=("Segoe UI", 14, "bold")).grid(row=row, column=1, sticky="ew", padx=12, pady=6)
                ctk.CTkLabel(table, text=last_month_score, anchor="e", font=("Segoe UI", 14)).grid(row=row, column=2, sticky="ew", padx=12, pady=6)
                ctk.CTkLabel(
                    table,
                    text=month_text,
                    width=82,
                    corner_radius=7,
                    fg_color=month_background,
                    anchor="e",
                    text_color=month_color,
                    font=("Segoe UI", 16, "bold"),
                ).grid(row=row, column=3, sticky="e", padx=12, pady=6)
                ctk.CTkLabel(table, text=year_text, anchor="e", text_color=year_color, font=("Segoe UI", 14, "bold")).grid(row=row, column=4, sticky="ew", padx=12, pady=6)

        switcher.configure(command=render)
        grade_menu.configure(command=render)
        search_text.trace_add("write", render)
        render()

    def close_score_trends(self) -> None:
        """Return from the in-window trends page to the dashboard."""
        if getattr(self, "trends_page", None) is not None:
            self.trends_page.destroy()
            self.trends_page = None
        self.dashboard_header.grid()
        self.dashboard_body.grid()

    def start_score_export(self) -> None:
        if self.busy:
            return
        self._export_score_history()

    def _export_score_history(self) -> None:
        def export() -> None:
            client, portfolio_id = self._client()
            portfolio_entries = client.fetch_portfolio_companies(portfolio_id)
            companies: list[Company] = []
            for item in portfolio_entries:
                domain = str(item.get("domain") or item.get("website") or "").strip()
                if not domain:
                    continue
                details = client.get_company(domain)
                companies.append(
                    Company(
                        str(details.get("domain") or domain),
                        str(details.get("name") or item.get("name") or domain),
                        str(details.get("grade") or "").upper(),
                        details.get("score"),
                    )
                )
            appended = append_score_history(companies, "Live portfolio")
            self.after(0, self._update_history_status)
            self._log(f"✓ Added {appended} live portfolio score records to {SCORE_HISTORY_PATH}.")
        self._run("Updating live portfolio score history", export)


def main() -> None:
    app = Dashboard()
    logging.getLogger().handlers.clear()
    logging.getLogger().addHandler(QueueLogHandler(app.log_queue))
    logging.getLogger().setLevel(logging.INFO)
    app.mainloop()


if __name__ == "__main__":
    main()
