window.Admin = (function () {
  function toast(message, kind) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.dataset.kind = kind || "info";
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => {
      el.hidden = true;
    }, 4000);
  }

  async function fetchJSON(url, options) {
    const resp = await fetch(url, Object.assign({ headers: { "Content-Type": "application/json" } }, options));
    let data = null;
    try {
      data = await resp.json();
    } catch (e) {
      /* kein JSON-Body */
    }
    if (!resp.ok) {
      const detail = data && data.detail ? data.detail : resp.statusText;
      throw new Error(detail || `HTTP ${resp.status}`);
    }
    return data;
  }

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  return { toast, fetchJSON, escapeHtml };
})();
