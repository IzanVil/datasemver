const SEVERITIES = ["major", "minor", "patch"];
const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const dom = {
  tabs: document.querySelectorAll(".tab"),
  views: {
    compare: document.getElementById("view-compare"),
    history: document.getElementById("view-history"),
  },
  form: document.getElementById("compare-form"),
  pickers: document.querySelectorAll(".picker"),
  guide: document.getElementById("guide"),
  uploadHint: document.getElementById("upload-hint"),
  status: document.getElementById("status"),
  result: document.getElementById("result"),
  summary: document.getElementById("summary"),
  badge: document.getElementById("bump-badge"),
  versionFrom: document.getElementById("version-from"),
  versionTo: document.getElementById("version-to"),
  sources: document.getElementById("summary-sources"),
  tally: document.getElementById("tally"),
  tallyBar: document.getElementById("tally-bar"),
  tallyLegend: document.getElementById("tally-legend"),
  statRows: document.getElementById("stat-rows"),
  statRowsDelta: document.getElementById("stat-rows-delta"),
  statColumns: document.getElementById("stat-columns"),
  statColumnsDelta: document.getElementById("stat-columns-delta"),
  statChanges: document.getElementById("stat-changes"),
  changes: document.querySelector("#changes-table tbody"),
  columns: document.querySelector("#columns-table tbody"),
  changelog: document.getElementById("changelog"),
  saveProfile: document.getElementById("save-profile"),
  copyChangelog: document.getElementById("copy-changelog"),
  historyPath: document.getElementById("history-path"),
  historyList: document.getElementById("history-list"),
  metaVersion: document.getElementById("meta-version"),
};

function showStatus(message, isError = false, isBusy = false) {
  dom.status.textContent = message;
  dom.status.classList.toggle("is-error", isError);
  dom.status.classList.toggle("is-busy", isBusy && !isError);
  dom.status.classList.toggle("is-hidden", !message);
}

function switchView(name) {
  dom.tabs.forEach((tab) => {
    const active = tab.dataset.view === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
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
    // A stored profile is offered on both sides: it is what makes a comparison against a
    // version too large to upload, or no longer on disk anywhere, possible from here.
    const accept = [...meta.supported_extensions, meta.profile_suffix].join(",");
    dom.form.querySelector('input[name="old"]').setAttribute("accept", accept);
    dom.form.querySelector('input[name="new"]').setAttribute("accept", accept);
    dom.uploadHint.textContent +=
      ` · either side may be a ${meta.profile_suffix} written by "Save profile"`;
  } catch (error) {
    dom.uploadHint.textContent = `Backend unreachable: ${error.message}`;
  }
}

// The file input lies over its picker, so what the picker shows is written here: the name of
// what was chosen, in place of the browser's own wording, which follows the browser's language.
dom.pickers.forEach((picker) => {
  const input = picker.querySelector('input[type="file"]');
  const label = picker.querySelector(".picker-file");

  input.addEventListener("change", () => {
    const file = input.files[0];
    picker.classList.toggle("has-file", Boolean(file));
    label.textContent = file ? `${file.name} · ${formatBytes(file.size)}` : label.dataset.empty;
  });

  ["dragenter", "dragover"].forEach((type) =>
    picker.addEventListener(type, () => picker.classList.add("is-over"))
  );
  ["dragleave", "drop"].forEach((type) =>
    picker.addEventListener(type, () => picker.classList.remove("is-over"))
  );
});

dom.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = dom.form.querySelector("button[type=submit]");
  const data = new FormData(dom.form);
  const rules = data.get("rules");
  if (rules && rules.size === 0) {
    data.delete("rules");
  }

  button.disabled = true;
  showStatus("Analysing…", false, true);
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

dom.saveProfile.addEventListener("click", async () => {
  const input = dom.form.querySelector('input[name="new"]');
  const file = input.files[0];
  if (!file) {
    showStatus("Choose a new version first: its profile is what gets saved.", true);
    return;
  }

  const data = new FormData();
  data.append("dataset", file);
  dom.saveProfile.disabled = true;
  showStatus("Profiling…", false, true);
  try {
    const profile = await request("/api/profile", { method: "POST", body: data });
    download(`${file.name.split(".")[0]}.profile.json`, JSON.stringify(profile, null, 2));
    showStatus("");
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    dom.saveProfile.disabled = false;
  }
});

function download(name, text) {
  // Held only long enough for the click: an object URL keeps its blob alive until it is
  // revoked, and a dashboard someone leaves open would accumulate them one profile at a time.
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = element("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

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
        "ul",
        { className: "history-versions", ariaLabel: `${dataset.versions.length} version(s)` },
        ...dataset.versions.map((version) =>
          element(
            "li",
            {},
            `v${version.version}`,
            element("small", {}, formatBytes(version.size_bytes))
          )
        )
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
      showStatus(`Analysing ${dataset.name}…`, false, true);
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
  dom.summary.dataset.bump = bump;
  dom.versionFrom.textContent = report.current_version;
  rollVersion(dom.versionTo, report.current_version, report.next_version);
  dom.sources.textContent = `${basename(report.old_source)} → ${basename(report.new_source)}`;
  dom.sources.title = `${report.old_source} → ${report.new_source}`;

  const { old: previous, new: current } = report.diff;
  const previousColumns = Object.keys(previous.columns).length;
  const currentColumns = Object.keys(current.columns).length;
  dom.statRows.textContent = `${previous.row_count} → ${current.row_count}`;
  dom.statColumns.textContent = `${previousColumns} → ${currentColumns}`;
  setDelta(dom.statRowsDelta, previous.row_count, current.row_count, true);
  setDelta(dom.statColumnsDelta, previousColumns, currentColumns, false);
  dom.statChanges.textContent = String(report.classified.length);

  renderTally(report.classified);
  renderChanges(report.classified);
  renderColumns(report.diff.columns);
  renderChangelog(buildChangelog(report));
  dom.guide.classList.add("is-hidden");
  dom.result.classList.remove("is-hidden");
  dom.result.scrollIntoView({ behavior: "smooth", block: "start" });
}

// The new version, rolled up from the one it replaces: each part counts from where it was to
// where it ends, so a bump is something that is seen happening and not only read afterwards.
// The text is the final version at every step it is not mid-roll, and a version that is not
// plain numbers, or a reader who asked for less motion, gets it at once.
function rollVersion(node, from, to) {
  const plain = /^\d+\.\d+\.\d+$/;
  const token = Symbol("roll");
  node.rolling = token;
  if (calm || from === to || !plain.test(from) || !plain.test(to)) {
    node.textContent = to;
    return;
  }
  const start = from.split(".").map(Number);
  const end = to.split(".").map(Number);
  const began = performance.now();
  const length = 750;
  const step = (now) => {
    if (node.rolling !== token) {
      return;
    }
    const progress = Math.min(1, (now - began) / length);
    const eased = 1 - (1 - progress) ** 3;
    node.textContent =
      progress === 1
        ? to
        : start.map((part, index) => Math.round(part + (end[index] - part) * eased)).join(".");
    if (progress < 1) {
      requestAnimationFrame(step);
    }
  };
  node.textContent = from;
  requestAnimationFrame(step);
}

// What a count moved by, said beside the count: "40 → 48" is arithmetic the reader should not
// have to do, and the share is what tells a few rows added to a big table from the opposite.
function setDelta(node, before, after, withShare) {
  const change = after - before;
  node.textContent = "";
  delete node.dataset.direction;
  if (change === 0) {
    return;
  }
  const sign = change > 0 ? "+" : "−";
  let text = `${sign}${Math.abs(change)}`;
  if (withShare && before > 0) {
    text += ` · ${sign}${Math.abs((change / before) * 100).toFixed(1).replace(/\.0$/, "")}%`;
  }
  node.textContent = text;
  node.dataset.direction = change > 0 ? "up" : "down";
}

function renderTally(classified) {
  dom.tallyBar.textContent = "";
  dom.tallyLegend.textContent = "";
  const counts = SEVERITIES.map((severity) => ({
    severity,
    count: classified.filter((item) => item.severity === severity).length,
  })).filter(({ count }) => count > 0);

  dom.tally.classList.toggle("is-hidden", counts.length === 0);
  counts.forEach(({ severity, count }, position) => {
    const segment = element("span", { dataset: { bump: severity } });
    segment.style.flexGrow = String(count);
    segment.style.setProperty("--n", String(position));
    dom.tallyBar.append(segment);
    dom.tallyLegend.append(
      element("li", { dataset: { bump: severity } }, `${count} ${severity}`)
    );
  });
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
        element("td", { className: "mono rule" }, item.rule || "—"),
        element("td", { className: "wrap" }, item.change.description)
      )
    );
  });
}

function renderColumns(columns) {
  dom.columns.textContent = "";
  columns.forEach((column) => {
    const name = column.renamed_from ? `${column.renamed_from} → ${column.name}` : column.name;
    const retyped = column.dtype_old !== column.dtype_new && column.status === "modified";
    dom.columns.append(
      element(
        "tr",
        { dataset: { status: column.status } },
        element("td", { className: "mono" }, name),
        element(
          "td",
          {},
          element("span", { className: "status-pill", dataset: { status: column.status } }, column.status)
        ),
        element(
          "td",
          { className: "mono" },
          column.dtype_old ?? "—",
          element("span", { className: "pair-arrow" }, "→"),
          element("span", { className: retyped ? "shifted" : "" }, column.dtype_new ?? "—")
        ),
        element(
          "td",
          {},
          percent(column.null_ratio_old),
          element("span", { className: "pair-arrow" }, "→"),
          element(
            "span",
            { className: nullsFell(column) ? "better" : "" },
            percent(column.null_ratio_new)
          )
        ),
        element(
          "td",
          {},
          `${column.cardinality_old ?? "—"}`,
          element("span", { className: "pair-arrow" }, "→"),
          `${column.cardinality_new ?? "—"}`
        )
      )
    );
  });
}

function nullsFell(column) {
  const before = column.null_ratio_old;
  const after = column.null_ratio_new;
  return before !== null && before !== undefined && after !== null && after !== undefined
    && after < before;
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

// Each heading takes the colour of its severity. The text stays whole, newlines included, so
// what "Copy" puts on the clipboard is exactly the entry and not a rendering of it.
function renderChangelog(text) {
  dom.changelog.textContent = "";
  text.split("\n").forEach((line, index) => {
    const kind = line.startsWith("### ")
      ? line.slice(4).toLowerCase()
      : line.startsWith("## ")
        ? "release"
        : "";
    dom.changelog.append(index > 0 ? "\n" : "", element("span", { className: kind ? `log-${kind}` : "" }, line));
  });
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

function basename(path) {
  return path.split("/").pop() || path;
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
