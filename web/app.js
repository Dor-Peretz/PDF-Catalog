const CATEGORY_LABELS = {
  חוזה: "Contracts",
  חשבונית: "Invoices",
  קבלה: "Receipts",
  דוח: "Reports",
  תעודה: "Certificates",
  מכתב: "Letters",
  אחר: "Other",
};

const LANGUAGE_LABELS = {
  he: "Hebrew",
  en: "English",
  "he+en": "Hebrew / English",
  unknown: "Unknown",
};

const state = {
  view: "list",
  selectedId: null,
  jobId: null,
  total: 0,
  matches: 0,
  documents: [],
  folder: "",
};

const els = {
  query: document.getElementById("query"),
  searchMeta: document.getElementById("search-meta"),
  results: document.getElementById("results"),
  categories: document.getElementById("category-filters"),
  details: document.getElementById("details"),
  detailsBody: document.getElementById("details-body"),
  empty: document.getElementById("empty-state"),
  settings: document.getElementById("settings"),
  progress: document.getElementById("progress-banner"),
  barFill: document.getElementById("bar-fill"),
  progressTitle: document.getElementById("progress-title"),
  progressCounts: document.getElementById("progress-counts"),
  progressFile: document.getElementById("progress-file"),
  pauseBtn: document.getElementById("pause-btn"),
  workspace: document.querySelector(".workspace"),
  sort: document.getElementById("sort"),
  sortLabel: document.getElementById("sort-label"),
  settingsFolder: document.getElementById("settings-folder"),
  dbStats: document.getElementById("db-stats"),
  titleFolder: document.getElementById("title-folder"),
  emptyFolder: document.getElementById("empty-folder"),
  folderPicker: document.getElementById("folder-picker"),
  pickerPath: document.getElementById("picker-path"),
  folderList: document.getElementById("folder-list"),
};

function icon(name) {
  return `<svg class="icon"><use href="#${name}"></use></svg>`;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return data;
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function hasHebrew(text) {
  return /[\u0590-\u05FF]/.test(String(text || ""));
}

function highlightSnippet(text) {
  const cls = hasHebrew(text) ? "rtl" : "ltr";
  const html = escapeHtml(text).replaceAll("[[", "<mark>").replaceAll("]]", "</mark>");
  return `<div class="doc-snippet ${cls}">${html}</div>`;
}

function formatBytes(size) {
  if (!size) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value) {
  if (!value) return "—";
  const date = Number(value) > 1000000000 && Number(value) < 100000000000 ? new Date(Number(value) * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function parentPath(path) {
  if (!path) return "";
  const parts = path.replaceAll("/", "\\").split("\\");
  parts.pop();
  return parts.join("\\");
}

function categoryLabel(value) {
  return CATEGORY_LABELS[value] || value || "Other";
}

function languageLabel(value) {
  return LANGUAGE_LABELS[value] || value || "Unknown";
}

function selectedCategories() {
  return [...document.querySelectorAll('#category-filters input[type="checkbox"]:checked')].map((el) => el.value);
}

function selectedOcr() {
  return [...document.querySelectorAll('#ocr-filters input[type="checkbox"]:checked')].map((el) => el.value);
}

function selectedLanguage() {
  const checked = document.querySelector('#language-filters input[name="language"]:checked');
  return checked ? checked.value : "";
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function setFolder(path) {
  state.folder = path || "";
  els.titleFolder.value = state.folder;
  els.settingsFolder.value = state.folder;
  if (els.emptyFolder) els.emptyFolder.value = state.folder;
}

async function loadStatus() {
  const data = await api("/api/status");
  state.total = data.documents;
  setFolder(data.folder || "");
  document.getElementById("opt-subfolders").checked = data.settings.scan_subfolders;
  document.getElementById("opt-ocr").checked = data.settings.run_ocr;
  document.getElementById("opt-language").checked = data.settings.detect_language;
  document.getElementById("opt-keywords").checked = data.settings.generate_keywords;
  document.getElementById("opt-heb").checked = data.settings.ocr_hebrew;
  document.getElementById("opt-eng").checked = data.settings.ocr_english;
  els.dbStats.textContent = `Indexed documents: ${data.documents.toLocaleString()} · Database size: ${formatBytes(data.database_size)}`;
  toggleEmpty(data.documents === 0 && !state.jobId);
  return data;
}

async function loadFilters() {
  const data = await api("/api/filters");
  const selected = new Set(selectedCategories());
  els.categories.innerHTML = (data.categories || [])
    .map(
      (item) => `
      <label class="filter-row">
        <input type="checkbox" value="${escapeHtml(item.category)}" ${selected.has(item.category) ? "checked" : ""} />
        ${escapeHtml(categoryLabel(item.category))}
        <span>${item.count}</span>
      </label>`
    )
    .join("") || `<p class="muted">No documents yet</p>`;

  const langCounts = Object.fromEntries((data.languages || []).map((item) => [item.language, item.count]));
  document.querySelectorAll("[data-lang-count]").forEach((el) => {
    const count = langCounts[el.dataset.langCount];
    el.textContent = count ? count : "";
  });
  document.querySelectorAll("[data-ocr-count]").forEach((el) => {
    const count = data.ocr?.[el.dataset.ocrCount];
    el.textContent = count ? count : "";
  });
}

async function search() {
  const params = new URLSearchParams();
  const query = els.query.value.trim();
  if (query) params.set("q", query);
  const cats = selectedCategories();
  if (cats.length) params.set("categories", cats.join(","));
  const language = selectedLanguage();
  if (language) params.set("language", language);
  const ocr = selectedOcr();
  if (ocr.length) params.set("ocr", ocr.join(","));
  params.set("sort", els.sort.value);
  const data = await api(`/api/search?${params.toString()}`);
  state.documents = data.results;
  state.matches = data.matches;
  state.total = data.total;
  const suffix = query || cats.length || language || ocr.length ? ` · ${data.matches} matches` : "";
  els.searchMeta.textContent = `${data.total.toLocaleString()} documents${suffix}`;
  els.sortLabel.textContent = `Sort: ${els.sort.selectedOptions[0].text}`;
  renderResults();
  toggleEmpty(data.total === 0 && !state.jobId);
}

function ocrStatus(doc) {
  if (doc.error) return { text: "OCR failed", cls: "warn", icon: "i-alert" };
  if (doc.is_scanned) return { text: "OCR completed", cls: "ok", icon: "i-check" };
  return { text: "Native PDF text", cls: "", icon: "i-file-text" };
}

function renderResults() {
  if (!state.documents.length) {
    els.results.innerHTML = `
      <div class="blank">
        <h2>No documents found</h2>
        <p>Try another search phrase or remove some filters.</p>
        <p>Search supports Hebrew and English.</p>
      </div>`;
    return;
  }

  if (state.view === "table") {
    els.results.innerHTML = `
      <table class="table">
        <thead>
          <tr>
            <th>Name</th><th>Category</th><th>Language</th><th>Pages</th><th>Modified</th>
          </tr>
        </thead>
        <tbody>
          ${state.documents
            .map(
              (doc) => `
            <tr data-id="${doc.id}" class="${doc.id === state.selectedId ? "selected" : ""}">
              <td>${escapeHtml(doc.filename)}</td>
              <td>${escapeHtml(categoryLabel(doc.category))}</td>
              <td>${escapeHtml(languageLabel(doc.language))}</td>
              <td>${doc.page_count || 0}</td>
              <td>${escapeHtml(formatDate(doc.mtime))}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
    return;
  }

  els.results.innerHTML = state.documents
    .map((doc) => {
      const keywords = (doc.keywords || [])
        .slice(0, 6)
        .map((item) => `<span class="tag">${escapeHtml(item.keyword)}</span>`)
        .join("");
      const status = ocrStatus(doc);
      return `
        <article class="doc-row ${doc.id === state.selectedId ? "selected" : ""}" data-id="${doc.id}">
          <div class="doc-icon">${icon("i-file-text")}</div>
          <div>
            <div class="doc-name">${escapeHtml(doc.filename)}</div>
            <div class="doc-meta">${escapeHtml(categoryLabel(doc.category))} · ${escapeHtml(languageLabel(doc.language))} · ${doc.page_count || 0} pages</div>
            <div class="doc-keywords">${keywords}</div>
            ${highlightSnippet(doc.snippet)}
            <div class="doc-path">${escapeHtml(doc.folder || parentPath(doc.path))}</div>
            <div class="status-line ${status.cls}">${icon(status.icon)} ${status.text}</div>
          </div>
        </article>`;
    })
    .join("");
}

function toggleEmpty(show) {
  els.empty.classList.toggle("hidden", !show);
}

function showDetails(open) {
  els.details.classList.toggle("hidden", !open);
  els.workspace.classList.toggle("with-details", open);
}

async function openDetails(id) {
  state.selectedId = Number(id);
  renderResults();
  const doc = await api(`/api/documents/${id}`);
  const status = ocrStatus(doc);
  const keywords = (doc.keywords || []).map((item) => `<span class="tag">${escapeHtml(item.keyword)}</span>`).join("") || "—";
  els.detailsBody.innerHTML = `
    <h3>${escapeHtml(doc.filename)}</h3>
    <dl class="prop"><dt>Location</dt><dd class="doc-path">${escapeHtml(doc.folder || parentPath(doc.path))}</dd></dl>
    <dl class="prop"><dt>Pages</dt><dd>${doc.page_count || 0}</dd></dl>
    <dl class="prop"><dt>Language</dt><dd>${escapeHtml(languageLabel(doc.language))}</dd></dl>
    <dl class="prop"><dt>Category</dt><dd>${escapeHtml(categoryLabel(doc.category))}</dd></dl>
    <dl class="prop"><dt>Keywords</dt><dd>${keywords}</dd></dl>
    <dl class="prop"><dt>Text extraction</dt><dd class="status-line ${status.cls}">${icon(status.icon)} ${status.text}</dd></dl>
    <dl class="prop"><dt>Indexed</dt><dd>${escapeHtml(formatDate(doc.indexed_at))}</dd></dl>
    ${doc.error ? `<dl class="prop"><dt>Error</dt><dd>${escapeHtml(doc.error)}</dd></dl>` : ""}
    <div class="details-actions">
      <button type="button" class="btn primary" data-open="${doc.id}">${icon("i-external")} Open PDF</button>
      <button type="button" class="btn" data-open-folder="${doc.id}">${icon("i-folder-open")} Open Folder</button>
      <button type="button" class="btn" data-reindex="${doc.id}">${icon("i-refresh")} Re-index</button>
    </div>`;
  showDetails(true);
}

let folderPickerResolve = null;
let pickerCurrent = "";
let pickerParent = "";

async function browseTo(path) {
  const data = await api(`/api/fs?path=${encodeURIComponent(path || "")}`);
  pickerCurrent = data.path || "";
  pickerParent = data.parent ?? "";
  els.pickerPath.value = pickerCurrent;
  if (!data.entries.length) {
    els.folderList.innerHTML = `<div class="folder-empty">No subfolders</div>`;
    return;
  }
  els.folderList.innerHTML = data.entries
    .map(
      (entry) => `
      <div class="folder-item" data-path="${escapeHtml(entry.path)}" data-parent="${data.parent ?? ""}">
        ${icon("i-folder")}
        <span class="name">${escapeHtml(entry.name)}</span>
      </div>`
    )
    .join("");
}

function openFolderPicker() {
  return new Promise((resolve) => {
    folderPickerResolve = resolve;
    els.folderPicker.classList.remove("hidden");
    browseTo(state.folder || els.titleFolder.value.trim() || els.emptyFolder.value.trim()).catch((err) => {
      els.folderList.innerHTML = `<div class="folder-empty">${escapeHtml(err.message)}</div>`;
    });
    els.pickerPath.focus();
  });
}

function closeFolderPicker(path) {
  els.folderPicker.classList.add("hidden");
  const resolve = folderPickerResolve;
  folderPickerResolve = null;
  if (resolve) resolve(path || null);
}

async function chooseFolder() {
  const path = await openFolderPicker();
  if (!path) return null;
  await api("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder: path }),
  });
  setFolder(path);
  return path;
}

async function startScan(options = {}) {
  const body = { ...options };
  const typed = (els.titleFolder.value || els.emptyFolder.value || "").trim();
  if (!body.path && !state.folder && !typed) {
    const picked = await chooseFolder();
    if (!picked) return;
    body.path = picked;
  } else if (!body.path) {
    body.path = state.folder || typed;
    setFolder(body.path);
  }
  const job = await api("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  state.jobId = job.id;
  toggleEmpty(false);
  await pollJob(job.id);
}

async function pollJob(jobId) {
  els.progress.classList.remove("hidden");
  while (true) {
    const job = await api(`/api/jobs/${jobId}`);
    const total = job.total || 0;
    const done = job.done || 0;
    const pct = total ? Math.round((done / total) * 100) : job.status === "queued" ? 0 : job.status === "done" ? 100 : 0;
    els.barFill.style.width = `${pct}%`;
    els.progressTitle.textContent = job.stage || "Indexing PDFs";
    els.progressCounts.textContent = total ? `${done} / ${total} documents · ${pct}%` : job.status;
    els.progressFile.textContent = job.current_file ? `Current file: ${job.current_file}` : "";
    els.pauseBtn.textContent = job.status === "paused" ? "Resume" : "Pause";
    if (["done", "error", "cancelled"].includes(job.status)) {
      state.jobId = null;
      els.progress.classList.add("hidden");
      await loadStatus();
      await loadFilters();
      await search();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

function setView(view) {
  state.view = view;
  document.getElementById("view-list").classList.toggle("active", view === "list");
  document.getElementById("view-table").classList.toggle("active", view === "table");
  els.results.classList.toggle("list-view", view === "list");
  renderResults();
}

document.getElementById("index-folder-btn").addEventListener("click", () => startScan().catch(alert));
document.getElementById("empty-select-btn").addEventListener("click", async () => {
  const typed = els.emptyFolder.value.trim() || els.titleFolder.value.trim();
  if (typed) {
    setFolder(typed);
    await startScan({ path: typed }).catch(alert);
    return;
  }
  startScan().catch(alert);
});
document.getElementById("browse-btn").addEventListener("click", () => chooseFolder().catch(alert));
document.getElementById("empty-browse-btn").addEventListener("click", () => chooseFolder().catch(alert));
document.getElementById("refresh-btn").addEventListener("click", () => startScan({ force: false }).catch(alert));
document.getElementById("settings-btn").addEventListener("click", () => els.settings.classList.remove("hidden"));
document.getElementById("close-settings").addEventListener("click", () => els.settings.classList.add("hidden"));
document.getElementById("close-details").addEventListener("click", () => showDetails(false));
document.getElementById("view-list").addEventListener("click", () => setView("list"));
document.getElementById("view-table").addEventListener("click", () => setView("table"));
document.getElementById("settings-browse").addEventListener("click", () => chooseFolder().catch(alert));
document.getElementById("folder-picker-close").addEventListener("click", () => closeFolderPicker(null));
document.getElementById("folder-picker-cancel").addEventListener("click", () => closeFolderPicker(null));
document.getElementById("folder-picker-select").addEventListener("click", () => {
  const path = (els.pickerPath.value.trim() || pickerCurrent).trim();
  if (!path) return;
  closeFolderPicker(path);
});
document.getElementById("picker-go").addEventListener("click", () => {
  browseTo(els.pickerPath.value.trim()).catch((err) => {
    els.folderList.innerHTML = `<div class="folder-empty">${escapeHtml(err.message)}</div>`;
  });
});
document.getElementById("picker-up").addEventListener("click", () => {
  browseTo(pickerParent).catch((err) => {
    els.folderList.innerHTML = `<div class="folder-empty">${escapeHtml(err.message)}</div>`;
  });
});
els.pickerPath.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    document.getElementById("picker-go").click();
  }
});
els.folderList.addEventListener("click", (event) => {
  const item = event.target.closest(".folder-item");
  if (!item) return;
  els.folderList.querySelectorAll(".folder-item").forEach((el) => el.classList.remove("selected"));
  item.classList.add("selected");
  pickerCurrent = item.dataset.path;
  els.pickerPath.value = item.dataset.path;
});
els.folderList.addEventListener("dblclick", (event) => {
  const item = event.target.closest(".folder-item");
  if (!item) return;
  browseTo(item.dataset.path).catch((err) => {
    els.folderList.innerHTML = `<div class="folder-empty">${escapeHtml(err.message)}</div>`;
  });
});
els.titleFolder.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    const path = els.titleFolder.value.trim();
    if (path) startScan({ path }).catch(alert);
  }
});
els.emptyFolder.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    document.getElementById("empty-select-btn").click();
  }
});
document.getElementById("save-settings").addEventListener("click", async () => {
  await api("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      folder: els.settingsFolder.value.trim(),
      scan_subfolders: document.getElementById("opt-subfolders").checked,
      run_ocr: document.getElementById("opt-ocr").checked,
      detect_language: document.getElementById("opt-language").checked,
      generate_keywords: document.getElementById("opt-keywords").checked,
      ocr_hebrew: document.getElementById("opt-heb").checked,
      ocr_english: document.getElementById("opt-eng").checked,
    }),
  });
  state.folder = els.settingsFolder.value.trim();
  els.settings.classList.add("hidden");
});
document.getElementById("rebuild-btn").addEventListener("click", async () => {
  if (!confirm("Rebuild the index from the current folder?")) return;
  els.settings.classList.add("hidden");
  await startScan({ rebuild: true, force: true });
});
document.getElementById("pause-btn").addEventListener("click", async () => {
  if (!state.jobId) return;
  const job = await api(`/api/jobs/${state.jobId}`);
  const action = job.status === "paused" ? "resume" : "pause";
  await api(`/api/jobs/${state.jobId}/${action}`, { method: "POST" });
});
document.getElementById("cancel-btn").addEventListener("click", async () => {
  if (!state.jobId) return;
  await api(`/api/jobs/${state.jobId}/cancel`, { method: "POST" });
});

els.query.addEventListener("input", debounce(() => search().catch(console.error), 200));
els.sort.addEventListener("change", () => search().catch(console.error));
els.categories.addEventListener("change", () => search().catch(console.error));
document.getElementById("language-filters").addEventListener("change", () => search().catch(console.error));
document.getElementById("ocr-filters").addEventListener("change", () => search().catch(console.error));

els.results.addEventListener("click", (event) => {
  const row = event.target.closest("[data-id]");
  if (row) openDetails(row.dataset.id).catch(alert);
});

els.detailsBody.addEventListener("click", async (event) => {
  const open = event.target.closest("[data-open]");
  const folder = event.target.closest("[data-open-folder]");
  const reindex = event.target.closest("[data-reindex]");
  try {
    if (open) await api(`/api/documents/${open.dataset.open}/open`, { method: "POST" });
    if (folder) await api(`/api/documents/${folder.dataset.openFolder}/open-folder`, { method: "POST" });
    if (reindex) {
      await api(`/api/documents/${reindex.dataset.reindex}/reindex`, { method: "POST" });
      await loadFilters();
      await search();
      await openDetails(reindex.dataset.reindex);
    }
  } catch (err) {
    alert(err.message);
  }
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    els.query.focus();
    els.query.select();
  }
  if (event.key === "Escape" && !els.folderPicker.classList.contains("hidden")) {
    closeFolderPicker(null);
  }
});

(async function init() {
  try {
    await loadStatus();
    await loadFilters();
    await search();
  } catch (err) {
    els.results.innerHTML = `<div class="blank"><h2>${escapeHtml(err.message)}</h2></div>`;
  }
})();
