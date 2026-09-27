(function () {
  const { fetchJSON, toast, escapeHtml } = window.Admin;
  let rows = [];

  function collectChain(startId, byId, edges, targetType) {
    const visited = new Set();
    const found = [];
    const queue = [startId];
    while (queue.length) {
      const current = queue.shift();
      edges
        .filter((e) => e.data.source === current)
        .forEach((e) => {
          const node = byId[e.data.target];
          if (!node || visited.has(node.id)) return;
          visited.add(node.id);
          if (node.type === targetType) found.push(node);
          // Weiter traversieren solange es ein Service ist – auch wenn der
          // Service selbst schon das gesuchte targetType ist (z. B. Service-Ketten
          // wie import_football_competition -> import_bundesliga -> ... -> Tabelle).
          if (node.type === "service") queue.push(node.id);
        });
    }
    return found;
  }

  function buildRows(graph) {
    const byId = {};
    graph.nodes.forEach((n) => {
      byId[n.data.id] = n.data;
    });
    const endpoints = graph.nodes.filter((n) => n.data.type === "endpoint").map((n) => n.data);

    return endpoints.map((ep) => {
      const services = collectChain(ep.id, byId, graph.edges, "service");
      const datasources = collectChain(ep.id, byId, graph.edges, "datasource");
      const serviceIds = new Set(services.map((s) => s.id));
      const tableEdges = graph.edges.filter(
        (e) => serviceIds.has(e.data.source) && byId[e.data.target] && byId[e.data.target].type === "table"
      );
      const tables = tableEdges.map((e) => `${byId[e.data.target].label} (${e.data.type})`);
      return {
        method: ep.method,
        path: ep.path,
        services: services.map((s) => s.label).join(", ") || "—",
        datasources: datasources.map((d) => d.label).join(", ") || "—",
        tables: tables.join(", ") || "—",
      };
    });
  }

  function render(filter) {
    const tbody = document.querySelector("#endpoints-table tbody");
    const filtered = rows.filter(
      (r) => !filter || (r.method + " " + r.path).toLowerCase().includes(filter.toLowerCase())
    );
    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="5">Keine Treffer.</td></tr>`;
      return;
    }
    tbody.innerHTML = filtered
      .map(
        (r) => `
      <tr>
        <td><span class="badge badge-method-${r.method}">${r.method}</span></td>
        <td class="mono">${escapeHtml(r.path)}</td>
        <td>${escapeHtml(r.services)}</td>
        <td>${escapeHtml(r.datasources)}</td>
        <td>${escapeHtml(r.tables)}</td>
      </tr>
    `
      )
      .join("");
  }

  async function load() {
    try {
      const graph = await fetchJSON("/admin/api/architecture");
      rows = buildRows(graph).sort((a, b) => (a.path + a.method).localeCompare(b.path + b.method));
      render("");
    } catch (err) {
      toast(`Fehler: ${err.message}`, "error");
    }
  }

  document.getElementById("endpoint-filter").addEventListener("input", (e) => render(e.target.value));
  load();
})();
