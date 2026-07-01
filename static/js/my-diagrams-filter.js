(function () {
  const diagramFilter = document.getElementById("diagram-filter");
  const sourceFilters = document.querySelectorAll("[data-source-filter]");
  const visibleCount = document.getElementById("diagram-visible-count");
  const filterEmpty = document.getElementById("diagram-filter-empty");
  let activeSource = "all";
  // Filtros de los desplegables buscables (solo en admin_diagrams).
  const filters = { province: "", client: "", site: "", tech: "" };

  function updateVisibleCount(visible) {
    if (!visibleCount) {
      return;
    }
    const label = visible === 1 ? "diagrama" : "diagramas";
    visibleCount.textContent = visible + " " + label;
  }

  function matchesDropdowns(row) {
    return (
      (!filters.province || (row.dataset.province || "") === filters.province) &&
      (!filters.client || (row.dataset.client || "") === filters.client) &&
      (!filters.site || (row.dataset.site || "") === filters.site) &&
      (!filters.tech || (row.dataset.tech || "") === filters.tech)
    );
  }

  function applyFilters() {
    const query = diagramFilter
      ? diagramFilter.value.toLocaleLowerCase("es").trim()
      : "";
    let visible = 0;
    document.querySelectorAll(".diagram-row").forEach(function (row) {
      const matchesSource =
        activeSource === "all" || row.dataset.source === activeSource;
      const matchesText =
        !query || row.textContent.toLocaleLowerCase("es").includes(query);
      const show = matchesSource && matchesText && matchesDropdowns(row);
      row.hidden = !show;
      if (show) {
        visible += 1;
      }
    });
    updateVisibleCount(visible);
    if (filterEmpty) {
      filterEmpty.hidden = visible > 0;
    }
  }

  if (diagramFilter) {
    diagramFilter.addEventListener("input", applyFilters);
  }

  sourceFilters.forEach(function (button) {
    button.addEventListener("click", function () {
      activeSource = button.dataset.sourceFilter || "all";
      sourceFilters.forEach(function (item) {
        item.classList.toggle("active", item === button);
      });
      applyFilters();
    });
  });

  // Desplegables buscables en cascada (provincia -> cliente -> sede + técnico).
  // La jerarquía se deriva de los diagramas listados, así solo se ofrecen valores
  // que existen y concuerdan (la provincia con su cliente, la sede con su cliente).
  function setupCascadeFilters() {
    const create = window.__drawioCreateSearchSelect;
    const provEl = document.getElementById("filter-province");
    if (!create || !provEl) {
      return;
    }
    const provClients = {}; // provincia -> {cliente: 1}
    const clientSites = {}; // cliente -> {sede: 1}
    const clientProvince = {}; // cliente -> provincia
    const techsSet = {};
    Array.prototype.slice.call(document.querySelectorAll(".diagram-row")).forEach(function (r) {
      const p = r.dataset.province || "", c = r.dataset.client || "", s = r.dataset.site || "", t = r.dataset.tech || "";
      if (t) techsSet[t] = 1;
      if (p) provClients[p] = provClients[p] || {};
      if (c) {
        provClients[p] = provClients[p] || {};
        provClients[p][c] = 1;
        clientProvince[c] = p;
        if (s) {
          clientSites[c] = clientSites[c] || {};
          clientSites[c][s] = 1;
        }
      }
    });
    const byName = function (a, b) { return a.toLocaleLowerCase("es").localeCompare(b.toLocaleLowerCase("es")); };
    const keys = function (o) { return Object.keys(o || {}).sort(byName); };
    const item = function (n, v) { return { nombre: n, value: v }; };
    const provinces = keys(provClients).filter(function (p) { return p; });
    const allClients = Object.keys(clientProvince).sort(byName);

    function provItems() {
      return [item("Todas las provincias", "")].concat(provinces.map(function (p) { return item(p, p); }));
    }
    function clientItems(prov) {
      const list = prov ? keys(provClients[prov]) : allClients;
      return [item("Todos los clientes", "")].concat(list.map(function (c) { return item(c, c); }));
    }
    function siteItems(client) {
      const list = client ? keys(clientSites[client]) : [];
      return [item("Todas las sedes", "")].concat(list.map(function (s) { return item(s, s); }));
    }
    function techItems() {
      return [item("Todos los técnicos", "")].concat(Object.keys(techsSet).sort(byName).map(function (t) { return item(t, t); }));
    }

    const provCtl = create(provEl, function (it) {
      filters.province = it.value;
      filters.client = "";
      filters.site = "";
      clientCtl.setItems(clientItems(it.value), "Todos los clientes");
      siteCtl.setItems(siteItems(""), "Todas las sedes");
      applyFilters();
    });
    const clientCtl = create(document.getElementById("filter-client"), function (it) {
      filters.client = it.value;
      filters.site = "";
      if (it.value && clientProvince[it.value]) {
        filters.province = clientProvince[it.value];
        provCtl.selectItem(item(filters.province, filters.province), { silent: true });
      }
      siteCtl.setItems(siteItems(it.value), "Todas las sedes");
      applyFilters();
    });
    const siteCtl = create(document.getElementById("filter-site"), function (it) {
      filters.site = it.value;
      applyFilters();
    });
    const techCtl = create(document.getElementById("filter-tech"), function (it) {
      filters.tech = it.value;
      applyFilters();
    });

    provCtl.setItems(provItems(), "Todas las provincias");
    clientCtl.setItems(clientItems(""), "Todos los clientes");
    siteCtl.setItems(siteItems(""), "Todas las sedes");
    techCtl.setItems(techItems(), "Todos los técnicos");
  }

  setupCascadeFilters();
  applyFilters();
})();
