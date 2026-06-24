(function () {
  const configElement = document.getElementById("diagram-glpi-config");
  if (!configElement) {
    return;
  }

  let config;
  try {
    config = JSON.parse(configElement.textContent);
  } catch (_error) {
    return;
  }

  const catalog = config.catalog || [];
  const province = document.getElementById("diagram-province");
  const customer = document.getElementById("diagram-customer");
  const site = document.getElementById("diagram-site");
  const entityId = document.getElementById("diagram-entity-id");
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
    const item = catalog.find(function (value) {
      return String(value.id) === province.value;
    });
    fill(customer, item ? item.clientes : [], "Selecciona un cliente");
    fill(site, [], "Selecciona primero un cliente");
    entityId.value = "";
  });
  customer.addEventListener("change", function () {
    const provinceItem = catalog.find(function (value) {
      return String(value.id) === province.value;
    });
    const item = provinceItem && provinceItem.clientes
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
