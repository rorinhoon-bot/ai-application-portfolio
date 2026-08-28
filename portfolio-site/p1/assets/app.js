"use strict";

(function renderEvidenceSite() {
  const evidence = globalThis.P1_EVIDENCE;
  if (!evidence || evidence.recorded_evidence !== true || evidence.live_service !== false) {
    document.body.dataset.evidenceError = "true";
    return;
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  function formatPercent(value) {
    return `${Math.round(value * 100)}%`;
  }

  function formatMilliseconds(value) {
    return `${(value / 1000).toFixed(3)}秒`;
  }

  function renderHeadlineMetrics() {
    const root = document.getElementById("headline-metrics");
    evidence.headline_metrics.forEach((metric) => {
      const card = element("article", "metric-card");
      card.append(
        element("span", "metric-label", metric.label),
        element("strong", "metric-value", metric.value),
        element("span", "metric-note", metric.note),
      );
      root.append(card);
    });
  }

  function renderComparison() {
    const root = document.getElementById("retrieval-comparison");
    evidence.retrieval_comparison.forEach((report) => {
      const recall = Math.round(report.recall_at_5 * 100);
      const row = element("article", "comparison-row");
      row.dataset.recall = String(recall);
      if (report.mode === "hybrid-client-rrf-v1") {
        row.classList.add("best");
      }

      const label = element("div", "comparison-label", report.label);
      label.append(element("small", "", report.mode));

      const track = element("div", "bar-track");
      track.setAttribute("role", "progressbar");
      track.setAttribute("aria-label", `${report.label} Recall@5`);
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", "100");
      track.setAttribute("aria-valuenow", String(recall));
      track.append(element("div", "bar-fill"));

      row.append(
        label,
        track,
        element("div", "comparison-number", formatPercent(report.recall_at_5)),
        element("div", "comparison-latency", `P95 ${formatMilliseconds(report.p95_ms)}`),
      );
      root.append(row);
    });
  }

  function renderArchitecture() {
    const root = document.getElementById("architecture-flow");
    evidence.architecture.forEach((item) => {
      const card = element("li", "architecture-step");
      card.append(
        element("span", "", item.step),
        element("h3", "", item.title),
        element("p", "", item.detail),
      );
      root.append(card);
    });
  }

  function citationCard(citation) {
    const card = element("article", "citation");
    const link = element(
      "a",
      "",
      `Python ${citation.python_version} · ${citation.section_path.join(" / ")}`,
    );
    link.href = citation.citation_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    card.append(link, element("p", "", citation.excerpt));
    return card;
  }

  function renderCases() {
    const tabs = document.getElementById("case-tabs");
    const panels = document.getElementById("case-panels");

    evidence.recorded_cases.forEach((item, index) => {
      const tabId = `case-tab-${index}`;
      const panelId = `case-panel-${index}`;
      const tab = element("button", "case-tab", item.label);
      tab.type = "button";
      tab.id = tabId;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panelId);
      tab.setAttribute("aria-selected", index === 0 ? "true" : "false");
      tab.tabIndex = index === 0 ? 0 : -1;

      const panel = element("section", "case-panel");
      panel.id = panelId;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tabId);
      panel.hidden = index !== 0;

      const summary = element("div", "case-summary");
      summary.append(
        element("span", "case-status", item.status),
        element("h3", "case-question", item.question),
        element(
          "p",
          "case-meta",
          `${item.model_name} · ${item.recorded_at} · build ${item.build_id}`,
        ),
      );

      const detail = element("div", "case-detail");
      detail.append(element("p", "case-answer", item.answer));
      const citationList = element("div", "citation-list");
      if (item.citations.length === 0) {
        citationList.append(element("p", "source-note", "无引用：系统因证据不足拒答。"));
      } else {
        item.citations.forEach((citation) => citationList.append(citationCard(citation)));
      }
      detail.append(citationList);

      if (item.review) {
        detail.append(
          element(
            "p",
            "review-note",
            `人工复核 ${item.review.decision}：${item.review.note} 原自动规则要求conflict，因此原correct=false；批准语义下accepted=true。`,
          ),
        );
      }

      panel.append(summary, detail);
      tabs.append(tab);
      panels.append(panel);

      tab.addEventListener("click", () => {
        tabs.querySelectorAll("[role='tab']").forEach((candidate) => {
          const selected = candidate === tab;
          candidate.setAttribute("aria-selected", selected ? "true" : "false");
          candidate.tabIndex = selected ? 0 : -1;
        });
        panels.querySelectorAll("[role='tabpanel']").forEach((candidate) => {
          candidate.hidden = candidate !== panel;
        });
      });
    });

    tabs.addEventListener("keydown", (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        return;
      }
      const tabItems = Array.from(tabs.querySelectorAll("[role='tab']"));
      const current = tabItems.indexOf(document.activeElement);
      if (current < 0) {
        return;
      }
      event.preventDefault();
      let next = current;
      if (event.key === "ArrowLeft") next = (current - 1 + tabItems.length) % tabItems.length;
      if (event.key === "ArrowRight") next = (current + 1) % tabItems.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabItems.length - 1;
      tabItems[next].focus();
      tabItems[next].click();
    });
  }

  function renderFailures() {
    const root = document.getElementById("failure-grid");
    evidence.failure_cases.forEach((item) => {
      const card = element("article", "failure-card");
      card.append(
        element("span", "failure-state", item.error_code || item.status),
        element("h3", "", item.label),
        element("p", "", item.evidence),
        element("p", "resolution", item.resolution),
      );
      root.append(card);
    });
  }

  function renderRuntime() {
    const root = document.getElementById("runtime-grid");
    const proof = evidence.runtime_proof;
    const items = [
      ["活动检索", proof.active_retrieval_mode],
      ["Qdrant points", String(proof.qdrant_points)],
      ["API运行用户", proof.api_user],
      ["只读rootfs", proof.api_read_only_rootfs ? "verified" : "not verified"],
      ["health / ready", `${proof.healthz} / ${proof.readyz}`],
      ["远程CI", "workflow-ready · 未运行"],
    ];
    items.forEach(([label, value]) => {
      const card = element("article", "runtime-card");
      card.append(element("span", "", label), element("strong", "", value));
      root.append(card);
    });
  }

  function renderLimitations() {
    const root = document.getElementById("limitations");
    evidence.limitations.forEach((item) => root.append(element("li", "", item)));
  }

  renderHeadlineMetrics();
  renderComparison();
  renderArchitecture();
  renderCases();
  renderFailures();
  renderRuntime();
  renderLimitations();
  document.body.dataset.evidenceReady = "true";
})();
