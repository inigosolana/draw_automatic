(function () {
  const diagramFilter = document.getElementById("diagram-filter");
  const sourceFilters = document.querySelectorAll("[data-source-filter]");
  const visibleCount = document.getElementById("diagram-visible-count");
  const filterEmpty = document.getElementById("diagram-filter-empty");
  let activeSource = "all";

  function updateVisibleCount(visible) {
    if (!visibleCount) {
      return;
    }
    const label = visible === 1 ? "diagrama" : "diagramas";
    visibleCount.textContent = visible + " " + label;
  }

  // Desplegables provincia/cliente/sede/técnico (solo en admin_diagrams).
  const dropdowns = Array.prototype.slice.call(
    document.querySelectorAll("[data-filter-key]")
  );

  function matchesDropdowns(row) {
    return dropdowns.every(function (sel) {
      const wanted = sel.value;
      if (!wanted) {
        return true;
      }
      return (row.dataset[sel.dataset.filterKey] || "") === wanted;
    });
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

  dropdowns.forEach(function (sel) {
    sel.addEventListener("change", applyFilters);
  });

  sourceFilters.forEach(function (button) {
    button.addEventListener("click", function () {
      activeSource = button.dataset.sourceFilter || "all";
      sourceFilters.forEach(function (item) {
        item.classList.toggle("active", item === button);
      });
      applyFilters();
    });
  });

  applyFilters();
})();
