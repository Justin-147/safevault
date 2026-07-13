document.addEventListener("DOMContentLoaded", () => {
  const formatLocalTime = (value) => {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleString([], {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const formatLocalTimes = (scope = document) => {
    scope.querySelectorAll("[data-local-time]").forEach((element) => {
      const value = element.getAttribute("datetime") || element.textContent;
      if (value) element.textContent = formatLocalTime(value);
    });
  };

  const localZoneLabel = () => {
    const offsetMinutes = -new Date().getTimezoneOffset();
    const sign = offsetMinutes >= 0 ? "+" : "-";
    const absolute = Math.abs(offsetMinutes);
    const hours = String(Math.floor(absolute / 60)).padStart(2, "0");
    const minutes = String(absolute % 60).padStart(2, "0");
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return `本机时间（UTC${sign}${hours}:${minutes}${zone ? `，${zone}` : ""}）`;
  };

  const appendFileCell = (row, entry) => {
    const cell = row.insertCell();
    cell.append(document.createTextNode(entry.rel_path));
    cell.append(document.createElement("br"));
    const root = document.createElement("small");
    root.textContent = entry.root_path;
    cell.append(root);
  };

  const appendTimeCell = (row, value) => {
    const cell = row.insertCell();
    const time = document.createElement("time");
    time.dateTime = value;
    time.dataset.localTime = "";
    time.textContent = formatLocalTime(value);
    cell.append(time);
  };

  const renderRecentDeleted = (entries) => {
    const body = document.querySelector("[data-recent-deleted]");
    if (!body) return;
    body.replaceChildren();
    if (!entries.length) {
      const row = body.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 3;
      cell.textContent = "最近没有删除记录。";
      return;
    }
    entries.forEach((entry) => {
      const row = body.insertRow();
      appendFileCell(row, entry);
      appendTimeCell(row, entry.detected_at);
      const action = row.insertCell();
      const form = document.createElement("form");
      form.method = "post";
      form.action = "/restore";
      [
        ["file", entry.absolute_path],
        ["mode", "latest"],
        ["confirmation", "CONFIRM"],
      ].forEach(([name, value]) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value;
        form.append(input);
      });
      const button = document.createElement("button");
      button.type = "submit";
      button.textContent = "恢复";
      form.append(button);
      form.addEventListener("submit", (event) => {
        if (!window.confirm("恢复到原位置？")) event.preventDefault();
      });
      action.append(form);
    });
  };

  const appendRestoreCell = (row, entry) => {
    const action = row.insertCell();
    const form = document.createElement("form");
    form.method = "post";
    form.action = "/restore";
    [
      ["file", entry.absolute_path],
      ["mode", "latest"],
      ["confirmation", "CONFIRM"],
    ].forEach(([name, value]) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      form.append(input);
    });
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = "恢复";
    form.append(button);
    form.addEventListener("submit", (event) => {
      if (!window.confirm("恢复到原位置？")) event.preventDefault();
    });
    action.append(form);
  };

  const renderDeletedList = (entries) => {
    const body = document.querySelector("[data-deleted-list]");
    if (!body) return;
    body.replaceChildren();
    if (!entries.length) {
      const row = body.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 4;
      cell.textContent = "这个时间范围内没有删除记录。";
      return;
    }
    entries.forEach((entry) => {
      const row = body.insertRow();
      row.insertCell().textContent = entry.root_path;
      row.insertCell().textContent = entry.rel_path;
      appendTimeCell(row, entry.detected_at);
      appendRestoreCell(row, entry);
    });
  };

  const eventLabels = {
    created: "新建",
    modified: "修改",
    restored: "恢复",
  };

  const renderRecentModified = (entries) => {
    const body = document.querySelector("[data-recent-modified]");
    if (!body) return;
    body.replaceChildren();
    if (!entries.length) {
      const row = body.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 3;
      cell.textContent = "最近没有修改记录。";
      return;
    }
    entries.forEach((entry) => {
      const row = body.insertRow();
      appendFileCell(row, entry);
      const event = row.insertCell();
      event.textContent = eventLabels[entry.event_type] || entry.event_type;
      appendTimeCell(row, entry.detected_at);
    });
  };

  formatLocalTimes();
  document.querySelectorAll("[data-local-zone]").forEach((element) => {
    element.textContent = localZoneLabel();
  });

  const deletedPage = document.querySelector("[data-deleted-live]");
  if (deletedPage) {
    const refreshStatus = document.querySelector("[data-deleted-refresh-status]");
    const since = deletedPage.dataset.since || "24h";
    let refreshInFlight = false;
    const refreshDeleted = async () => {
      if (refreshInFlight || document.hidden) return;
      refreshInFlight = true;
      try {
        const response = await fetch(`/api/deleted?since=${encodeURIComponent(since)}`, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        renderDeletedList(payload.deleted || []);
        if (refreshStatus) {
          refreshStatus.textContent = `刚刚更新 · ${localZoneLabel()}`;
        }
      } catch (_error) {
        if (refreshStatus) {
          refreshStatus.textContent = `自动更新暂时不可用 · ${localZoneLabel()}`;
        }
      } finally {
        refreshInFlight = false;
      }
    };
    window.setTimeout(refreshDeleted, 1000);
    window.setInterval(refreshDeleted, 5000);
  }

  const dashboard = document.querySelector("[data-dashboard-live]");
  if (dashboard) {
    const refreshStatus = document.querySelector("[data-dashboard-refresh-status]");
    let refreshInFlight = false;
    const refreshDashboard = async () => {
      if (refreshInFlight || document.hidden) return;
      refreshInFlight = true;
      try {
        const response = await fetch("/api/dashboard/recent", {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        renderRecentDeleted(payload.deleted || []);
        renderRecentModified(payload.modified || []);
        if (refreshStatus) refreshStatus.textContent = "刚刚更新";
      } catch (_error) {
        if (refreshStatus) refreshStatus.textContent = "自动更新暂时不可用，可刷新页面";
      } finally {
        refreshInFlight = false;
      }
    };
    window.setTimeout(refreshDashboard, 1000);
    window.setInterval(refreshDashboard, 5000);
  }

  const container = document.querySelector("[data-custom-roots]");
  const addButton = document.querySelector("[data-add-custom-root]");

  const bindRemove = (row) => {
    const button = row.querySelector("[data-remove-custom-root]");
    if (!button) return;
    button.addEventListener("click", () => {
      const rows = container?.querySelectorAll("[data-custom-root-row]") ?? [];
      if (rows.length === 1) {
        const input = row.querySelector("input");
        if (input) input.value = "";
        return;
      }
      row.remove();
    });
  };

  if (container && addButton) {
    container.querySelectorAll("[data-custom-root-row]").forEach(bindRemove);
    addButton.addEventListener("click", () => {
      const first = container.querySelector("[data-custom-root-row]");
      if (!first) return;
      const clone = first.cloneNode(true);
      const input = clone.querySelector("input");
      if (input) input.value = "";
      container.insertBefore(clone, addButton);
      bindRemove(clone);
      input?.focus();
    });
  }

  const skipRoots = document.querySelector("[data-skip-roots]");
  const syncSkippedRoots = () => {
    if (!skipRoots) return;
    document.querySelectorAll("input[name='roots']").forEach((input) => {
      input.disabled = skipRoots.checked;
    });
    container?.querySelectorAll("input, select, button").forEach((control) => {
      control.disabled = skipRoots.checked;
    });
  };
  skipRoots?.addEventListener("change", syncSkippedRoots);
  syncSkippedRoots();

  const form = document.querySelector("[data-onboarding-form]");
  form?.addEventListener("submit", () => {
    const button = form.querySelector("button[type='submit']");
    if (!button) return;
    button.disabled = true;
    button.textContent = button.dataset.submitLabel || "正在处理…";
  });

  if (document.querySelector("[data-storage-migration-active]")) {
    window.setTimeout(() => window.location.reload(), 3000);
  }
});
