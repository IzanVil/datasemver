const SEVERITIES = ["major", "minor", "patch"];

const dom = {
  tabs: document.querySelectorAll(".tab"),
  views: {
    compare: document.getElementById("view-compare"),
    history: document.getElementById("view-history"),
  },
  form: document.getElementById("compare-form"),
  uploadHint: document.getElementById("upload-hint"),
  status: document.getElementById("status"),
  result: document.getElementById("result"),
  badge: document.getElementById("bump-badge"),
  versionFrom: document.getElementById("version-from"),
  versionTo: document.getElementById("version-to"),
  sources: document.getElementById("summary-sources"),
  statRows: document.getElementById("stat-rows"),
  statColumns: document.getElementById("stat-columns"),
  statChanges: document.getElementById("stat-changes"),
  changes: document.querySelector("#changes-table tbody"),
  columns: document.querySelector("#columns-table tbody"),
  changelog: document.getElementById("changelog"),
  copyChangelog: document.getElementById("copy-changelog"),
  historyPath: document.getElementById("history-path"),
  historyList: document.getElementById("history-list"),
  metaVersion: document.getElementById("meta-version"),
};

function showStatus(message, isError = false) {
  dom.status.textContent = message;
  dom.status.classList.toggle("is-error", isError);
  dom.status.classList.toggle("is-hidden", !message);
}

function switchView(name) {
  dom.tabs.forEach((tab) => tab.classList.toggle("is-active", tab.dataset.view === name));
  Object.entries(dom.views).forEach(([key, view]) => {
    view.classList.toggle("is-hidden", key !== name);
  });
  if (name === "history") {
    loadHistory();
  }
}

async function request(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

async function loadMeta() {
  try {
    const meta = await request("/api/meta");
    dom.metaVersion.textContent = meta.version;
    dom.uploadHint.textContent =
      `Accepted: ${meta.supported_extensions.join(", ")} · up to ${meta.max_upload_mb} MB per file`;
    const accept = meta.supported_extensions.join(",");
    dom.form.querySelector('input[name="old"]').setAttribute("accept", accept);
    dom.form.querySelector('input[name="new"]').setAttribute("accept", accept);
  } catch (error) {
    dom.uploadHint.textContent = `Backend unreachable: ${error.message}`;
  }
}

dom.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = dom.form.querySelector("button[type=submit]");
  const data = new FormData(dom.form);
  const rules = data.get("rules");
  if (rules && rules.size === 0) {
    data.delete("rules");
  }

  button.disabled = true;
  showStatus("Analysing…");
  dom.result.classList.add("is-hidden");
  try {
    const report = await request("/api/diff", { method: "POST", body: data });
    renderReport(report);
    showStatus("");
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
});

async function loadHistory() {
  dom.historyList.textContent = "Loading…";
  try {
    const history = await request("/api/history");
    dom.historyPath.textContent = history.directory;
    renderHistory(history);
  } catch (error) {
    dom.historyList.textContent = "";
    showStatus(error.message, true);
  }
}

function renderHistory(history) {
  dom.historyList.textContent = "";

  if (!history.exists) {
    dom.historyList.append(
      element("p", { className: "muted" }, "The datasets directory does not exist yet.")
    );
    return;
  }
  if (history.datasets.length === 0) {
    dom.historyList.append(
      element(
        "p",
        { className: "muted" },
        "No versioned datasets found. Name the files like customers_v1.csv and customers_v2.csv."
      )
    );
    return;
  }

  history.datasets.forEach((dataset) => {
    const item = element("div", { className: "history-item" });
    item.append(element("h3", {}, dataset.name));
    item.append(
      element(
        "p",
        { className: "history-versions" },
        `${dataset.versions.length} version(s): ${dataset.versions
          .map((version) => `v${version.version} (${formatBytes(version.size_bytes)})`)
          .join(" · ")}`
      )
    );

    const options = dataset.versions.map((version) =>
      element("option", { value: version.version }, `v${version.version} — ${version.filename}`)
    );
    const oldSelect = element("select", {}, ...options.map((option) => option.cloneNode(true)));
    const newSelect = element("select", {}, ...options.map((option) => option.cloneNode(true)));
    oldSelect.selectedIndex = Math.max(0, dataset.versions.length - 2);
    newSelect.selectedIndex = dataset.versions.length - 1;

    const button = element("button", { className: "button", type: "button" }, "Compare");
    button.disabled = dataset.versions.length < 2;
    button.title = button.disabled ? "Add a second version to compare" : "";
    button.addEventListener("click", async () => {
      button.disabled = true;
      showStatus(`Analysing ${dataset.name}…`);
      dom.result.classList.add("is-hidden");
      try {
        const query = new URLSearchParams({ old: oldSelect.value, new: newSelect.value });
        const report = await request(
          `/api/history/${encodeURIComponent(dataset.name)}/diff?${query}`
        );
        renderReport(report);
        showStatus("");
      } catch (error) {
        showStatus(error.message, true);
      } finally {
        button.disabled = false;
      }
    });

    item.append(
      element(
        "div",
        { className: "history-controls" },
        labelled("From", oldSelect),
        labelled("To", newSelect),
        button
      )
    );
    dom.historyList.append(item);
  });
}

function renderReport(report) {
  const bump = report.bump || "none";
  dom.badge.textContent = bump;
  dom.badge.dataset.bump = bump;
  dom.versionFrom.textContent = report.current_version;
  dom.versionTo.textContent = report.next_version;
  dom.sources.textContent = `${report.old_source} → ${report.new_source}`;

  const { old: previous, new: current } = report.diff;
  dom.statRows.textContent = `${previous.row_count} → ${current.row_count}`;
  dom.statColumns.textContent =
    `${Object.keys(previous.columns).length} → ${Object.keys(current.columns).length}`;
  dom.statChanges.textContent = String(report.classified.length);

  renderChanges(report.classified);
  renderColumns(report.diff.columns);
  dom.changelog.textContent = buildChangelog(report);
  dom.result.classList.remove("is-hidden");
  dom.result.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderChanges(classified) {
  dom.changes.textContent = "";
  if (classified.length === 0) {
    dom.changes.append(
      element("tr", {}, element("td", { colSpan: 3, className: "muted" }, "No changes detected."))
    );
    return;
  }

  const ordered = [...classified].sort(
    (left, right) => rank(right.severity) - rank(left.severity)
  );
  ordered.forEach((item) => {
    const severity = item.severity || "unclassified";
    dom.changes.append(
      element(
        "tr",
        {},
        element(
          "td",
          {},
          element("span", { className: "severity", dataset: { severity } }, severity.toUpperCase())
        ),
        element("td", { className: "mono" }, item.rule || "—"),
        element("td", { className: "wrap" }, item.change.description)
      )
    );
  });
}

function renderColumns(columns) {
  dom.columns.textContent = "";
  columns.forEach((column) => {
    const name = column.renamed_from ? `${column.renamed_from} → ${column.name}` : column.name;
    dom.columns.append(
      element(
        "tr",
        {},
        element("td", { className: "mono" }, name),
        element(
          "td",
          {},
          element("span", { className: "status-pill", dataset: { status: column.status } }, column.status)
        ),
        element("td", { className: "mono" }, `${column.dtype_old ?? "—"} → ${column.dtype_new ?? "—"}`),
        element("td", {}, `${percent(column.null_ratio_old)} → ${percent(column.null_ratio_new)}`),
        element("td", {}, `${column.cardinality_old ?? "—"} → ${column.cardinality_new ?? "—"}`)
      )
    );
  });
}

function buildChangelog(report) {
  const lines = [`## [${report.next_version}] - ${report.generated_at}`, ""];
  SEVERITIES.forEach((severity) => {
    const items = report.classified.filter((item) => item.severity === severity);
    if (items.length === 0) {
      return;
    }
    lines.push(`### ${severity.charAt(0).toUpperCase()}${severity.slice(1)}`);
    items.forEach((item) => lines.push(`- ${item.change.description}`));
    lines.push("");
  });
  if (lines.length === 2) {
    lines.push("No classified changes detected.");
  }
  return lines.join("\n").trim();
}

dom.copyChangelog.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(dom.changelog.textContent);
    dom.copyChangelog.textContent = "Copied";
  } catch {
    dom.copyChangelog.textContent = "Copy failed";
  }
  setTimeout(() => {
    dom.copyChangelog.textContent = "Copy";
  }, 1500);
});

dom.tabs.forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));

function element(tag, properties = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(properties).forEach(([key, value]) => {
    if (key === "dataset") {
      Object.assign(node.dataset, value);
    } else {
      node[key] = value;
    }
  });
  children.forEach((child) => node.append(child));
  return node;
}

function labelled(text, control) {
  return element(
    "label",
    { className: "field" },
    element("span", { className: "field-label" }, text),
    control
  );
}

function rank(severity) {
  const index = SEVERITIES.indexOf(severity);
  return index === -1 ? -1 : SEVERITIES.length - index;
}

function percent(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function formatBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

loadMeta();
