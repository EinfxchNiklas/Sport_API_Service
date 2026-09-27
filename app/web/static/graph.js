(function () {
  const { fetchJSON, toast, escapeHtml } = window.Admin;

  const TYPE_COLORS = {
    endpoint: "#5b8def",
    service: "#8b5cf6",
    datasource: "#f59e0b",
    table: "#10b981",
    job: "#ef4444",
  };

  let cy;

  function render(graph) {
    if (cy) cy.destroy();
    cy = cytoscape({
      container: document.getElementById("cy"),
      elements: graph,
      style: [
        {
          selector: "node",
          style: {
            "background-color": (el) => TYPE_COLORS[el.data("type")] || "#94a3b8",
            label: "data(label)",
            color: "#e2e8f0",
            "font-size": 10,
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 6,
            width: 22,
            height: 22,
            "border-width": 2,
            "border-color": "#1e293b",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#475569",
            "target-arrow-color": "#475569",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            opacity: 0.7,
          },
        },
        {
          selector: "edge[type = 'writes']",
          style: { "line-color": "#ef4444", "target-arrow-color": "#ef4444" },
        },
        {
          selector: "edge[type = 'reads']",
          style: { "line-color": "#10b981", "target-arrow-color": "#10b981" },
        },
        {
          selector: "edge[type = 'triggers']",
          style: { "line-style": "dashed", "line-color": "#f59e0b", "target-arrow-color": "#f59e0b" },
        },
      ],
      layout: { name: "cose", animate: false, padding: 40 },
    });

    cy.on("tap", "node", (evt) => showNodeInfo(evt.target));
  }

  function showNodeInfo(node) {
    const data = node.data();
    const connected = node.connectedEdges().map((edge) => {
      const source = edge.source().data();
      const target = edge.target().data();
      const other = source.id === data.id ? target : source;
      const direction = source.id === data.id ? "→" : "←";
      return `<li>${direction} <strong>${escapeHtml(other.label)}</strong> <span class="muted">(${edge.data("type")})</span></li>`;
    });
    document.getElementById("node-info").innerHTML = `
      <h3>${escapeHtml(data.label)}</h3>
      <span class="badge badge-ok">${escapeHtml(data.type)}</span>
      ${data.detail ? `<p class="muted">${escapeHtml(data.detail)}</p>` : ""}
      <ul class="edge-list">${connected.join("") || "<li>Keine Verbindungen</li>"}</ul>
    `;
  }

  async function load() {
    const graph = await fetchJSON("/admin/api/architecture");
    render(graph);
  }

  document.getElementById("regenerate-btn").addEventListener("click", async () => {
    try {
      const graph = await fetchJSON("/admin/api/architecture/regenerate", { method: "POST" });
      render(graph);
      toast("Graph neu generiert", "success");
    } catch (err) {
      toast(`Fehler: ${err.message}`, "error");
    }
  });

  load().catch((err) => toast(`Fehler beim Laden: ${err.message}`, "error"));
})();
