(function () {
  var configElement = document.getElementById("admin-dashboard-config");
  if (!configElement) {
    return;
  }

  var config;
  try {
    config = JSON.parse(configElement.textContent);
  } catch (_error) {
    return;
  }

  var chartPeriods = config.chartPeriods || {};
  var periodTitles = {
    week: { chart: "Diagramas últimos 7 días", top: "Top técnicos (7 días)" },
    month: { chart: "Diagramas últimos 30 días", top: "Top técnicos (30 días)" },
    year: { chart: "Diagramas últimos 12 meses", top: "Top técnicos (12 meses)" },
  };

  var ctx = document.getElementById("activityChart");
  var activityChart = null;
  var gradient = null;
  if (ctx && typeof Chart !== "undefined") {
    var chartCtx = ctx.getContext("2d");
    gradient = chartCtx.createLinearGradient(0, 0, 0, ctx.height || 220);
    gradient.addColorStop(0, "rgba(1,105,111,0.35)");
    gradient.addColorStop(1, "rgba(1,105,111,0.02)");

    activityChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: chartPeriods.week.labels,
        datasets: [
          {
            label: "Diagramas publicados",
            data: chartPeriods.week.values,
            backgroundColor: gradient,
            borderColor: "#01696f",
            borderWidth: 2,
            borderRadius: 4,
            hoverBackgroundColor: "rgba(1,105,111,0.55)",
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#0f1d28",
            titleColor: "#fff",
            bodyColor: "#fff",
            padding: 10,
            cornerRadius: 8,
            displayColors: false,
            callbacks: {
              label: function (item) {
                var n = item.parsed.y;
                return n + (n === 1 ? " diagrama" : " diagramas");
              },
            },
          },
        },
        scales: {
          x: {
            ticks: { maxRotation: 45, autoSkip: true, maxTicksLimit: 15 },
          },
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 } },
        },
      },
    });
  }

  function renderTopTechnicians(period) {
    var data = chartPeriods[period];
    var list = document.getElementById("topTechBody");
    var empty = document.getElementById("topTechEmpty");
    if (!list || !empty) {
      return;
    }

    list.innerHTML = "";
    if (!data.top.length) {
      empty.classList.add("is-visible");
      return;
    }
    empty.classList.remove("is-visible");

    var maxCount = Math.max(1, ...data.top.map(function (row) {
      return row.count;
    }));
    data.top.forEach(function (row) {
      var li = document.createElement("li");
      li.className = "top-tech-row";

      var name = document.createElement("span");
      name.className = "top-tech-name";
      name.textContent = row.name;
      name.title = row.name;

      var barWrap = document.createElement("span");
      barWrap.className = "top-tech-bar-wrap";
      var bar = document.createElement("span");
      var bucket = Math.max(1, Math.min(10, Math.ceil((row.count / maxCount) * 10)));
      bar.className = "top-tech-bar bar-w-" + bucket;
      barWrap.appendChild(bar);

      var count = document.createElement("span");
      count.className = "top-tech-count";
      count.textContent = row.count;

      li.append(name, barWrap, count);
      list.appendChild(li);
    });
  }

  function setPeriod(period) {
    var data = chartPeriods[period];
    if (!data) {
      return;
    }

    if (activityChart) {
      activityChart.data.labels = data.labels;
      activityChart.data.datasets[0].data = data.values;
      activityChart.update();
    }

    var titles = periodTitles[period];
    document.getElementById("chartTitle").textContent = titles.chart;
    document.getElementById("topTechTitle").textContent = titles.top;
    renderTopTechnicians(period);
  }

  document.querySelectorAll(".period-filter").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".period-filter").forEach(function (button) {
        button.classList.remove("active");
      });
      btn.classList.add("active");
      setPeriod(btn.dataset.period);
    });
  });

  setPeriod("week");

  var rows = Array.from(document.querySelectorAll("#secTable .sec-row"));
  var emptyMsg = document.getElementById("secEmpty");
  var activeLevel = "ALL";
  var searchTerm = "";

  function applyFilters() {
    var visible = 0;
    rows.forEach(function (row) {
      var level = row.dataset.level;
      var text = row.textContent.toLowerCase();
      var matchLevel = activeLevel === "ALL" || level === activeLevel;
      var matchSearch = !searchTerm || text.includes(searchTerm);
      row.classList.toggle("is-hidden", !(matchLevel && matchSearch));
      if (matchLevel && matchSearch) {
        visible += 1;
      }
    });
    if (emptyMsg) {
      emptyMsg.classList.toggle("is-visible", visible === 0);
    }
  }

  document.querySelectorAll(".sec-filter").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".sec-filter").forEach(function (button) {
        button.classList.remove("active");
      });
      btn.classList.add("active");
      activeLevel = btn.dataset.level;
      applyFilters();
    });
  });

  var searchInput = document.getElementById("secSearch");
  if (searchInput) {
    searchInput.addEventListener("input", function (event) {
      searchTerm = event.target.value.toLowerCase().trim();
      applyFilters();
    });
  }

  var exportButton = document.getElementById("exportCsv");
  if (exportButton) {
    exportButton.addEventListener("click", function () {
      var visibleRows = rows.filter(function (row) {
        return !row.classList.contains("is-hidden");
      });
      var lines = [["Fecha/Hora", "Nivel", "Mensaje"].join(";")];
      visibleRows.forEach(function (row) {
        var cells = Array.from(row.querySelectorAll("td")).map(function (td) {
          return '"' + td.textContent.trim().replace(/"/g, '""') + '"';
        });
        lines.push(cells.join(";"));
      });
      var blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
      var anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(blob);
      anchor.download = "security_events.csv";
      anchor.click();
    });
  }
})();
