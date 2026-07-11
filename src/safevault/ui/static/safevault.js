document.addEventListener("DOMContentLoaded", () => {
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
