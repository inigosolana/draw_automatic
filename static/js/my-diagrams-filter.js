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
      const show = matchesSource && matchesText;
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

  applyFilters();
})();
