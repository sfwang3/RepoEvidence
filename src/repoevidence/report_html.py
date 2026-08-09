"""Offline document chrome and visual system for RepoEvidence reports."""

# ruff: noqa: E501

from __future__ import annotations

from html import escape

from repoevidence import __version__
from repoevidence.i18n import message
from repoevidence.report_view import ReportViewModel


class ReportHtmlRenderer:
    """Render a self-contained, accessible HTML document around report sections."""

    def render(self, view: ReportViewModel, body_html: str) -> str:
        language = view.language
        name = _safe(view.repository.name)
        title = _safe(message("report.title", language, name=view.repository.name))
        generated = _safe(view.generated_at.isoformat())
        repository_path = _safe(view.repository.path)
        return f"""<!doctype html>
<html lang="{_safe(language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>{title}</title>
  <style>{REPORT_CSS}</style>
</head>
<body>
  <a class="skip-link" href="#main">{_safe(message("report.skip_link", language))}</a>
  <header class="site-header">
    <div class="header-inner">
      <div class="identity-mark">
        <strong>RepoEvidence</strong>
        <span>{_safe(message("report.header.kind", language))}</span>
      </div>
      <div class="snapshot-identity">
        <h1>{name}</h1>
        <code>{repository_path}</code>
      </div>
      <div class="generated-meta" aria-label="{_safe(message("report.generated_aria", language))}">
        <span>{_safe(message("report.generated", language))}</span>
        <time datetime="{generated}">{generated}</time>
        <small>{_safe(message("report.tool_version", language, version=__version__))}</small>
      </div>
    </div>
    <nav class="section-nav" aria-label="{_safe(message("report.nav.label", language))}">
      <a href="#summary">{_safe(message("report.nav.summary", language))}</a>
      <a href="#coverage">{_safe(message("report.nav.coverage", language))}</a>
      <a href="#project">{_safe(message("report.nav.project", language))}</a>
      <a href="#ledger">{_safe(message("report.nav.evidence", language))}</a>
    </nav>
  </header>
  <main id="main" class="shell">
    {body_html}
  </main>
  <footer class="footer">{_safe(message("report.footer", language))}</footer>
  <script>{REPORT_JS}</script>
</body>
</html>
"""


def _safe(value: object) -> str:
    return escape(str(value), quote=True)


REPORT_CSS = r"""
:root {
  color-scheme: light dark;
  --page: #f4f3ef;
  --surface: #fbfaf7;
  --surface-raised: #ffffff;
  --ink: #17201f;
  --ink-soft: #53605e;
  --ink-faint: #77817f;
  --line: #d8ddda;
  --line-strong: #b8c2be;
  --accent: #176b5b;
  --accent-soft: #dcece7;
  --attention: #986117;
  --attention-soft: #f6ead5;
  --danger: #9a3d42;
  --danger-soft: #f7e3e4;
  --info: #33677e;
  --info-soft: #e1edf2;
  --code: #eef0ed;
  --focus: #247eeb;
  --shadow: 0 8px 28px rgb(26 39 36 / 7%);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font: 16px/1.6 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
code, pre, input, .eyebrow, .status-pill, .method, .section-index, .generated-meta {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}
code { overflow-wrap: anywhere; }
a { color: var(--accent); text-underline-offset: .18em; }
a:hover { text-decoration-thickness: 2px; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; }
h1, h2, h3, p { margin-top: 0; }
h2 { margin-bottom: 0; font-size: clamp(1.45rem, 2.5vw, 2.1rem); line-height: 1.15; letter-spacing: -.025em; }
h3 { margin-bottom: 0; font-size: 1rem; }

.skip-link { position: fixed; top: 8px; left: -999px; z-index: 20; padding: 10px 14px; background: var(--surface-raised); color: var(--ink); border: 1px solid var(--line-strong); }
.skip-link:focus { left: 8px; }
.site-header { background: var(--surface); border-bottom: 1px solid var(--line); }
.header-inner { max-width: 1120px; margin: auto; padding: 24px; display: grid; grid-template-columns: 180px minmax(0, 1fr) minmax(210px, auto); gap: 28px; align-items: end; }
.identity-mark { display: grid; gap: 2px; }
.identity-mark strong { color: var(--accent); letter-spacing: -.02em; }
.identity-mark span { color: var(--ink-soft); font-size: .78rem; }
.snapshot-identity { min-width: 0; }
.snapshot-identity h1 { margin: 0 0 2px; font-size: clamp(1.35rem, 3vw, 2rem); line-height: 1.15; letter-spacing: -.035em; }
.snapshot-identity code { display: block; color: var(--ink-soft); font-size: .78rem; }
.generated-meta { display: grid; justify-items: end; gap: 2px; color: var(--ink-soft); font-size: .72rem; }
.generated-meta time { color: var(--ink); }
.section-nav { max-width: 1120px; margin: auto; padding: 0 24px 14px; display: flex; gap: 22px; overflow-x: auto; }
.section-nav a { color: var(--ink-soft); font-size: .78rem; font-weight: 650; text-decoration: none; white-space: nowrap; }
.section-nav a:hover { color: var(--accent); }
.shell { max-width: 1120px; margin: auto; padding: 0 24px; }
.section { padding: 58px 0; border-bottom: 1px solid var(--line); scroll-margin-top: 16px; }
.section-heading { display: flex; justify-content: space-between; gap: 24px; align-items: start; margin-bottom: 22px; }
.section-index { color: var(--ink-faint); font-size: .72rem; }
.eyebrow { margin-bottom: 8px; color: var(--accent); font-size: .7rem; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.section-note { max-width: 72ch; color: var(--ink-soft); }
.label { display: block; margin-bottom: 5px; color: var(--ink-soft); font: 700 .68rem/1.35 ui-monospace, monospace; letter-spacing: .06em; text-transform: uppercase; }

.summary-section { padding-top: 54px; }
.conclusion-layout { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(250px, .75fr); gap: 18px; }
.conclusion-card { min-height: 250px; padding: clamp(26px, 5vw, 48px); background: var(--ink); color: var(--surface); display: flex; flex-direction: column; justify-content: space-between; box-shadow: var(--shadow); }
.conclusion-card .eyebrow { color: #80cbbb; }
.conclusion-card h2 { max-width: 24ch; font-size: clamp(2rem, 5vw, 3.6rem); letter-spacing: -.05em; }
.conclusion-card p { max-width: 65ch; margin: 24px 0 0; color: #c9d2d0; }
.boundary-card { padding: 26px; border: 1px solid var(--line); background: var(--surface); display: flex; flex-direction: column; justify-content: space-between; }
.boundary-card p { color: var(--ink-soft); }
.next-action { margin-top: 26px; padding-top: 22px; border-top: 1px solid var(--line); }
.next-action strong { display: block; margin-bottom: 7px; }
.command { display: block; margin-top: 12px; padding: 11px 13px; background: var(--code); border: 1px solid var(--line); color: var(--ink); }

.coverage-list { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 0; padding: 0; list-style: none; }
.coverage-item { position: relative; padding: 21px; min-height: 148px; background: var(--surface); border: 1px solid var(--line); }
.coverage-item::before { content: ""; position: absolute; top: 0; right: 0; left: 0; height: 3px; background: var(--line-strong); }
.coverage-item.state-current::before { background: var(--accent); }
.coverage-item.state-failed::before { background: var(--danger); }
.coverage-item.state-stale::before, .coverage-item.state-not_run::before { background: var(--attention); }
.coverage-item.state-unknown::before { background: var(--info); }
.coverage-item strong { display: block; margin: 8px 0 5px; font-size: 1.05rem; }
.coverage-item p { margin: 0; color: var(--ink-soft); font-size: .88rem; }
.state-label { color: var(--ink-soft); font: 700 .68rem/1.3 ui-monospace, monospace; letter-spacing: .05em; text-transform: uppercase; }

.attention-layout { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(260px, .6fr); gap: 18px; }
.attention-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.attention-item { padding: 15px 17px; background: var(--attention-soft); border-left: 3px solid var(--attention); }
.attention-item.kind-drift, .attention-item.kind-database_verification_failed, .attention-item.kind-comparison_failed { background: var(--danger-soft); border-color: var(--danger); }
.attention-item code { display: block; margin-top: 5px; color: var(--ink-soft); font-size: .75rem; }
.empty-note, .empty-state, .unavailable { color: var(--ink-soft); }
.empty-state { padding: 22px; border: 1px dashed var(--line-strong); background: var(--surface); display: grid; gap: 4px; }

.identity-grid { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 1px; margin: 24px 0; padding: 1px; background: var(--line); }
.identity-grid > div { min-width: 0; padding: 17px; background: var(--surface); }
.identity-grid code, .identity-grid strong { display: block; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.stat-card { min-height: 108px; padding: 16px; background: var(--surface); border: 1px solid var(--line); display: flex; flex-direction: column; justify-content: space-between; }
.stat-card span, .mini-stat span { color: var(--ink-soft); font: 700 .67rem/1.3 ui-monospace, monospace; letter-spacing: .05em; text-transform: uppercase; }
.stat-card strong { font-size: 1.65rem; font-variant-numeric: tabular-nums; }
.stat-card.unavailable strong { color: var(--ink-faint); font-size: 1rem; }

.table-wrap { margin: 17px 0; overflow-x: auto; border: 1px solid var(--line); background: var(--surface); }
table { width: 100%; min-width: 620px; border-collapse: collapse; }
th, td { padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { background: var(--code); color: var(--ink-soft); font: 700 .68rem/1.35 ui-monospace, monospace; letter-spacing: .05em; text-transform: uppercase; }
tr:last-child td { border-bottom: 0; }
.mini-stat-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 20px 0; }
.mini-stat { min-height: 76px; padding: 13px; background: var(--surface); border: 1px solid var(--line); }
.mini-stat strong { display: block; margin-top: 7px; font-size: 1.2rem; }
.drift-banner, .match-banner, .runtime-banner, .stale-banner { margin: 20px 0; padding: 16px 18px; border: 1px solid; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.drift-banner { color: var(--danger); background: var(--danger-soft); border-color: color-mix(in srgb, var(--danger), var(--line) 50%); }
.match-banner, .runtime-banner { color: var(--accent); background: var(--accent-soft); border-color: color-mix(in srgb, var(--accent), var(--line) 55%); }
.stale-banner { color: var(--attention); background: var(--attention-soft); border-color: color-mix(in srgb, var(--attention), var(--line) 55%); }
.flyway-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 20px 0; }
.flyway-compare > div { padding: 18px; background: var(--surface); border: 1px solid var(--line); }
.subheading { margin: 28px 0 11px; display: flex; justify-content: space-between; gap: 16px; align-items: baseline; }
.subheading span { color: var(--ink-soft); font: .72rem ui-monospace, monospace; }
.finding { margin: 8px 0; padding: 17px; background: var(--surface); border: 1px solid var(--line); border-left: 3px solid var(--accent); }
.finding-runtime_only, .finding-source_only, .finding-version_mismatch, .finding-runtime_failed, .finding-ambiguous { border-left-color: var(--attention); }
.finding-top { display: flex; gap: 9px; align-items: center; flex-wrap: wrap; }
.finding-top > code { margin-left: auto; color: var(--ink-soft); font-size: .72rem; }
.status-pill { display: inline-flex; padding: 3px 7px; color: var(--ink-soft); background: var(--code); border: 1px solid var(--line-strong); font-size: .67rem; }
.compact-dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; }
.compact-dl dt { color: var(--ink-soft); }
.compact-dl dd { margin: 0; }
.reference-block { margin-top: 13px; padding-top: 12px; border-top: 1px solid var(--line); }
.reference-block ul, .plain-list { margin: 7px 0 0; padding: 0; list-style: none; display: grid; gap: 6px; }
.reference-block li, .plain-list li { display: flex; gap: 9px; align-items: baseline; flex-wrap: wrap; }

.section-toolbar { margin-bottom: 14px; display: flex; justify-content: space-between; gap: 20px; align-items: end; color: var(--ink-soft); }
.section-toolbar p { max-width: 66ch; margin: 0; }
.section-toolbar label { min-width: 250px; display: grid; gap: 6px; color: var(--ink-soft); font: 700 .68rem ui-monospace, monospace; text-transform: uppercase; }
.section-toolbar input { min-height: 44px; padding: 9px 11px; border: 1px solid var(--line-strong); background: var(--surface-raised); color: var(--ink); font: inherit; }
.endpoint-list, .ledger { display: grid; gap: 7px; }
.endpoint-row, .fact-row, .recorded-comparison { background: var(--surface); border: 1px solid var(--line); }
summary { cursor: pointer; }
.endpoint-row summary, .fact-row summary { min-height: 50px; padding: 12px 14px; display: grid; grid-template-columns: 76px minmax(150px, 2fr) 1fr 1fr 100px; gap: 10px; align-items: center; }
.method { width: max-content; padding: 3px 7px; color: #fff; background: var(--info); font-size: .7rem; font-weight: 750; }
.method-get { background: var(--accent); }
.method-delete { background: var(--danger); }
.detail-grid { padding: 18px; border-top: 1px solid var(--line); display: grid; grid-template-columns: repeat(2, 1fr); gap: 17px; }
.detail-grid > div { min-width: 0; }
.maven-group { margin-top: 24px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 7px; }
.tag { padding: 6px 9px; background: var(--accent-soft); border: 1px solid var(--line-strong); }
.fact-row summary { grid-template-columns: 12px 92px minmax(200px, 2fr) minmax(170px, 2fr) 145px; }
.fact-row summary em { color: var(--ink-soft); font: .7rem ui-monospace, monospace; font-style: normal; text-align: right; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line-strong); }
.status-declared { color: var(--attention); }
.status-inferred { color: var(--info); }
.status-verified { color: var(--accent); }
.status-conflicted { color: var(--danger); }
.fact-detail { padding: 18px; border-top: 1px solid var(--line); }
.code-block { max-height: 340px; margin: 8px 0; padding: 13px; overflow: auto; white-space: pre-wrap; word-break: break-word; background: var(--code); border: 1px solid var(--line); color: var(--ink); font: .76rem/1.55 ui-monospace, monospace; }
.recorded-comparison { margin-top: 18px; padding: 14px 16px; }
.recorded-comparison > div { padding-top: 12px; }
.footer { max-width: 1120px; margin: auto; padding: 28px 24px 56px; color: var(--ink-soft); font-size: .8rem; }

@media (prefers-color-scheme: dark) {
  :root {
    --page: #111615;
    --surface: #171d1c;
    --surface-raised: #1d2422;
    --ink: #e6ece9;
    --ink-soft: #aab7b3;
    --ink-faint: #84918d;
    --line: #303a37;
    --line-strong: #4a5753;
    --accent: #79c8b6;
    --accent-soft: #19372f;
    --attention: #e2b46d;
    --attention-soft: #3d2d1b;
    --danger: #e38b90;
    --danger-soft: #3d2426;
    --info: #8abbd0;
    --info-soft: #1d3039;
    --code: #202725;
    --focus: #78aef5;
    --shadow: none;
  }
  .conclusion-card { background: #e1e9e6; color: #12201d; }
  .conclusion-card .eyebrow { color: #176b5b; }
  .conclusion-card p { color: #44534f; }
}

@media (max-width: 900px) {
  .header-inner { grid-template-columns: 150px 1fr; }
  .generated-meta { grid-column: 2; justify-items: start; }
  .conclusion-layout, .attention-layout { grid-template-columns: 1fr; }
  .coverage-list { grid-template-columns: 1fr; }
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .mini-stat-grid { grid-template-columns: repeat(3, 1fr); }
  .identity-grid { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 560px) {
  .header-inner { grid-template-columns: 1fr; gap: 18px; padding: 20px 16px; }
  .generated-meta { grid-column: auto; justify-items: start; }
  .section-nav { padding-inline: 16px; }
  .shell { padding-inline: 16px; }
  .section { padding: 42px 0; }
  .summary-section { padding-top: 34px; }
  .conclusion-card { min-height: 0; }
  .stat-grid, .mini-stat-grid, .identity-grid, .flyway-compare, .detail-grid { grid-template-columns: 1fr; }
  .section-toolbar { display: grid; align-items: stretch; }
  .section-toolbar label { min-width: 0; }
  .endpoint-row summary, .fact-row summary { grid-template-columns: 28px 1fr; }
  .endpoint-row summary > *, .fact-row summary > * { grid-column: 2; }
  .fact-row summary em { text-align: left; }
  .footer { padding-inline: 16px; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}

@media print {
  :root { color-scheme: light; }
  body { background: #fff; color: #111; }
  .site-header, .section, .footer { background: #fff; }
  .section-nav, .skip-link, input { display: none !important; }
  .shell, .header-inner, .footer { max-width: none; padding-inline: 0; }
  .section { break-inside: avoid; }
  details { break-inside: avoid; }
  .conclusion-card { background: #fff; color: #111; border: 2px solid #111; box-shadow: none; }
  .conclusion-card p { color: #333; }
  a { color: inherit; text-decoration: none; }
}
"""


REPORT_JS = r"""
(() => {
  const input = document.querySelector('[data-endpoint-filter]');
  if (!input) return;
  const rows = Array.from(document.querySelectorAll('[data-endpoint-row]'));
  input.addEventListener('input', () => {
    const query = input.value.trim().toLowerCase();
    rows.forEach((row) => {
      row.hidden = query !== '' && !row.textContent.toLowerCase().includes(query);
    });
  });
})();
"""
