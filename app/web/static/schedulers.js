(function () {
  const { fetchJSON, toast, escapeHtml } = window.Admin;

  function fmtDate(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleString("de-DE");
  }

  async function load() {
    try {
      const data = await fetchJSON("/admin/api/schedulers");
      renderStatus(data.status);
      renderJobs(data.jobs);
      renderHistory(data.history);
    } catch (err) {
      toast(`Fehler beim Laden: ${err.message}`, "error");
    }
  }

  function renderStatus(status) {
    document.getElementById("scheduler-status").innerHTML = `
      <div class="card"><span class="card-label">Status</span><span class="card-value">${status.running ? "läuft" : "gestoppt"}</span></div>
      <div class="card"><span class="card-label">Jobs</span><span class="card-value">${status.job_count}</span></div>
      <div class="card"><span class="card-label">Zeitzone</span><span class="card-value">${escapeHtml(status.timezone)}</span></div>
      <div class="card"><span class="card-label">enable_scheduler</span><span class="card-value">${status.enabled ? "true" : "false"}</span></div>
    `;
  }

  function renderJobs(jobs) {
    const tbody = document.querySelector("#jobs-table tbody");
    if (!jobs.length) {
      tbody.innerHTML = `<tr><td colspan="5">Keine Jobs registriert (Scheduler evtl. deaktiviert – enable_scheduler=false).</td></tr>`;
      return;
    }
    tbody.innerHTML = jobs
      .map(
        (job) => `
      <tr>
        <td>${escapeHtml(job.name)}</td>
        <td class="mono">${escapeHtml(job.trigger)}</td>
        <td>${fmtDate(job.next_run_time)}</td>
        <td><span class="badge ${job.paused ? "badge-warn" : "badge-ok"}">${job.paused ? "pausiert" : "aktiv"}</span></td>
        <td class="actions-cell">
          <button class="btn btn-sm" data-job="${escapeHtml(job.id)}" data-op="${job.paused ? "resume" : "pause"}">${job.paused ? "Fortsetzen" : "Pausieren"}</button>
          <button class="btn btn-sm btn-primary" data-job="${escapeHtml(job.id)}" data-op="run">Run now</button>
        </td>
      </tr>
    `
      )
      .join("");

    tbody.querySelectorAll("button[data-op]").forEach((btn) => {
      btn.addEventListener("click", () => runOp(btn.dataset.job, btn.dataset.op));
    });
  }

  function renderHistory(history) {
    const tbody = document.querySelector("#history-table tbody");
    if (!history.length) {
      tbody.innerHTML = `<tr><td colspan="4">Noch keine Ausführungen protokolliert.</td></tr>`;
      return;
    }
    tbody.innerHTML = history
      .map(
        (h) => `
      <tr>
        <td>${fmtDate(h.timestamp)}</td>
        <td class="mono">${escapeHtml(h.job_id)}</td>
        <td><span class="badge ${h.status === "success" ? "badge-ok" : h.status === "missed" ? "badge-warn" : "badge-error"}">${h.status}</span></td>
        <td>${h.error ? escapeHtml(h.error) : "—"}</td>
      </tr>
    `
      )
      .join("");
  }

  async function runOp(jobId, op) {
    try {
      await fetchJSON(`/admin/api/schedulers/${encodeURIComponent(jobId)}/${op}`, { method: "POST" });
      toast(`${jobId}: ${op} ausgeführt`, "success");
      load();
    } catch (err) {
      toast(`Fehler: ${err.message}`, "error");
    }
  }

  document.getElementById("refresh-jobs").addEventListener("click", load);
  load();
  setInterval(load, 15000);
})();
