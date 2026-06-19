(function () {
  var configElement = document.getElementById("upload-glpi-config");
  if (!configElement || typeof window.__drawioCreateSearchSelect !== "function") {
    return;
  }

  var config;
  try {
    config = JSON.parse(configElement.textContent);
  } catch (_error) {
    return;
  }

  var catalog = config.catalog || [];
  var createSearchSelect = window.__drawioCreateSearchSelect;
  var siteControl = createSearchSelect(document.getElementById("upload-site"), function (site) {
    document.getElementById("upload-entity-id").value = site.id;
    document.getElementById("upload-site-name").value = site.nombre;
  });
  var customerControl = createSearchSelect(document.getElementById("upload-customer"), function (customer) {
    document.getElementById("upload-client-name").value = customer.nombre;
    document.getElementById("upload-entity-id").value = "";
    siteControl.setItems(customer.sedes, "Selecciona una sede");
  });
  var provinceControl = createSearchSelect(document.getElementById("upload-province"), function (province) {
    customerControl.setItems(province.clientes, "Selecciona un cliente");
    siteControl.setItems([], "Selecciona primero un cliente");
  });
  provinceControl.setItems(catalog, "Selecciona una provincia");

  document.addEventListener("click", function (event) {
    if (!event.target.closest(".search-select")) {
      document.querySelectorAll(".search-select.open").forEach(function (element) {
        element.classList.remove("open");
      });
    }
  });
})();
