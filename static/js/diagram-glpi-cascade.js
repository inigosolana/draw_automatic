(function () {
  var configElement = document.getElementById("diagram-glpi-config");
  if (!configElement) {
    return;
  }

  var config;
  try {
    config = JSON.parse(configElement.textContent);
  } catch (_error) {
    return;
  }

  var catalog = config.catalog || [];
  var province = document.getElementById("diagram-province");
  var customer = document.getElementById("diagram-customer");
  var site = document.getElementById("diagram-site");
  var entityId = document.getElementById("diagram-entity-id");
  if (!province || !customer || !site || !entityId) {
    return;
  }

  function fill(select, items, placeholder) {
    select.innerHTML = "";
    select.append(new Option(placeholder, ""));
    items.forEach(function (item) {
      select.append(new Option(item.nombre, String(item.id)));
    });
    select.disabled = !items.length;
  }

  fill(province, catalog, "Selecciona una provincia");
  province.addEventListener("change", function () {
    var item = catalog.find(function (value) {
      return String(value.id) === province.value;
    });
    fill(customer, item ? item.clientes : [], "Selecciona un cliente");
    fill(site, [], "Selecciona primero un cliente");
    entityId.value = "";
  });
  customer.addEventListener("change", function () {
    var provinceItem = catalog.find(function (value) {
      return String(value.id) === province.value;
    });
    var item = provinceItem && provinceItem.clientes
      ? provinceItem.clientes.find(function (value) {
          return String(value.id) === customer.value;
        })
      : null;
    fill(site, item ? item.sedes : [], "Selecciona una sede");
    entityId.value = "";
  });
  site.addEventListener("change", function () {
    entityId.value = site.value;
  });
})();
