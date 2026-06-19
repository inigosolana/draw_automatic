(function () {
  var diagramFilter = document.getElementById("diagram-filter");
  if (!diagramFilter) {
    return;
  }

  diagramFilter.addEventListener("input", function () {
    var query = diagramFilter.value.toLocaleLowerCase("es").trim();
    document.querySelectorAll(".diagram-row").forEach(function (row) {
      row.hidden = query && !row.textContent.toLocaleLowerCase("es").includes(query);
    });
  });
})();
