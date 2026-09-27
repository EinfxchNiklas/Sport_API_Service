(function () {
  const { fetchJSON, toast, escapeHtml } = window.Admin;

  async function loadOverview() {
    const el = document.getElementById("overview-cards");
    try {
      const data = await fetchJSON("/admin/api/overview");
      const s = data.scheduler;
      const cards = [
        `<div class="card"><span class="card-label">Scheduler</span><span class="card-value">${s.running ? "läuft" : "gestoppt"}</span><span class="card-sub">${s.job_count} Jobs · ${escapeHtml(s.timezone)}</span></div>`,
      ];
      for (const [label, count] of Object.entries(data.counts)) {
        cards.push(
          `<div class="card"><span class="card-label">${escapeHtml(label)}</span><span class="card-value">${count}</span></div>`
        );
      }
      el.innerHTML = cards.join("");
    } catch (err) {
      el.innerHTML = `<div class="card alert-error">Fehler: ${escapeHtml(err.message)}</div>`;
    }
  }

  function collectParams(spec) {
    if (!spec) return {};
    const params = {};
    for (const pair of spec.split(",")) {
      const [inputId, key] = pair.split(":");
      const input = document.getElementById(inputId);
      if (!input) continue;
      params[key] = input.type === "number" ? Number(input.value) : input.value;
    }
    return params;
  }

  function log(message) {
    const el = document.getElementById("action-log");
    const ts = new Date().toLocaleTimeString("de-DE");
    const prev = el.textContent === "Noch keine Aktionen ausgeführt." ? "" : el.textContent;
    el.textContent = `[${ts}] ${message}\n${prev}`;
  }

  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      const params = collectParams(btn.dataset.params);
      const useBody = btn.hasAttribute("data-body");
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = "Läuft…";
      try {
        const url = useBody
          ? `/admin/api/actions/${action}`
          : `/admin/api/actions/${action}?${new URLSearchParams(params).toString()}`;
        const result = await fetchJSON(url, {
          method: "POST",
          body: useBody ? JSON.stringify(params) : undefined,
        });
        if (result.ok) {
          toast(`${action}: erfolgreich`, "success");
          log(`${action} OK → ${JSON.stringify(result.result)}`);
        } else {
          toast(`${action}: fehlgeschlagen`, "error");
          log(`${action} FEHLER → ${result.error}`);
        }
        loadOverview();
      } catch (err) {
        toast(`${action}: ${err.message}`, "error");
        log(`${action} FEHLER → ${err.message}`);
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  });

  loadOverview();
})();
