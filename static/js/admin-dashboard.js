(function () {
  const configElement = document.getElementById("admin-dashboard-config");
  if (!configElement) {
    return;
  }

  let config;
  try {
    config = JSON.parse(configElement.textContent);
  } catch (_error) {
    return;
  }

  const chartPeriods = config.chartPeriods || {};
  const periodTitles = {
    week: { chart: "Diagramas últimos 7 días", top: "Top técnicos (7 días)" },
    month: { chart: "Diagramas últimos 30 días", top: "Top técnicos (30 días)" },
    year: { chart: "Diagramas últimos 12 meses", top: "Top técnicos (12 meses)" },
  };

  const ctx = document.getElementById("activityChart");
  let activityChart = null;
  let gradient = null;
  if (ctx && typeof Chart !== "undefined") {
    const chartCtx = ctx.getContext("2d");
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
                const n = item.parsed.y;
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
    const data = chartPeriods[period];
    const list = document.getElementById("topTechBody");
    const empty = document.getElementById("topTechEmpty");
    if (!list || !empty) {
      return;
    }

    list.innerHTML = "";
    if (!data.top.length) {
      empty.classList.add("is-visible");
      return;
    }
    empty.classList.remove("is-visible");

    const maxCount = Math.max(1, ...data.top.map(function (row) {
      return row.count;
    }));
    data.top.forEach(function (row) {
      const li = document.createElement("li");
      li.className = "top-tech-row";

      const name = document.createElement("span");
      name.className = "top-tech-name";
      name.textContent = row.name;
      name.title = row.name;

      const barWrap = document.createElement("span");
      barWrap.className = "top-tech-bar-wrap";
      const bar = document.createElement("span");
      const bucket = Math.max(1, Math.min(10, Math.ceil((row.count / maxCount) * 10)));
      bar.className = "top-tech-bar bar-w-" + bucket;
      barWrap.appendChild(bar);

      const count = document.createElement("span");
      count.className = "top-tech-count";
      count.textContent = row.count;

      li.append(name, barWrap, count);
      list.appendChild(li);
    });
  }

  function setPeriod(period) {
    const data = chartPeriods[period];
    if (!data) {
      return;
    }

    if (activityChart) {
      activityChart.data.labels = data.labels;
      activityChart.data.datasets[0].data = data.values;
      activityChart.update();
    }

    const titles = periodTitles[period];
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

  const rows = Array.from(document.querySelectorAll("#secTable .sec-row"));
  const emptyMsg = document.getElementById("secEmpty");
  let activeLevel = "ALL";
  let searchTerm = "";

  function applyFilters() {
    let visible = 0;
    rows.forEach(function (row) {
      const level = row.dataset.level;
      const text = row.textContent.toLowerCase();
      const matchLevel = activeLevel === "ALL" || level === activeLevel;
      const matchSearch = !searchTerm || text.includes(searchTerm);
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

  const searchInput = document.getElementById("secSearch");
  if (searchInput) {
    searchInput.addEventListener("input", function (event) {
      searchTerm = event.target.value.toLowerCase().trim();
      applyFilters();
    });
  }

  const exportButton = document.getElementById("exportCsv");
  if (exportButton) {
    exportButton.addEventListener("click", function () {
      const visibleRows = rows.filter(function (row) {
        return !row.classList.contains("is-hidden");
      });
      const lines = [["Fecha/Hora", "Nivel", "Mensaje"].join(";")];
      visibleRows.forEach(function (row) {
        const cells = Array.from(row.querySelectorAll("td")).map(function (td) {
          return '"' + td.textContent.trim().replace(/"/g, '""') + '"';
        });
        lines.push(cells.join(";"));
      });
      const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(blob);
      anchor.download = "security_events.csv";
      anchor.click();
    });
  }
})();
