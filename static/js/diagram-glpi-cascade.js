(function () {
  const configElement = document.getElementById("diagram-glpi-config");
  if (!configElement || typeof window.__drawioCreateSearchSelect !== "function") {
    return;
  }

  let config;
  try {
    config = JSON.parse(configElement.textContent);
  } catch (_error) {
    return;
  }

  const catalog = config.catalog || [];
  const selectedEntityId = String(config.selectedEntityId || "");
  const createSearchSelect = window.__drawioCreateSearchSelect;
  const entityId = document.getElementById("diagram-entity-id");
  const form = document.getElementById("diagram-search-form");

  if (!entityId) {
    return;
  }

  // Lista plana de todos los clientes con su provincia, para poder buscar por
  // cliente sin elegir provincia primero (igual que en Crear diagrama).
  const customerProvince = new Map();
  const allCustomers = [];
  catalog.forEach(function (province) {
    (province.clientes || []).forEach(function (customer) {
      customerProvince.set(customer, province);
      allCustomers.push(customer);
    });
  });

  const siteControl = createSearchSelect(document.getElementById("diagram-site"), function (site) {
    entityId.value = String(site.id);
  });
  const customerControl = createSearchSelect(document.getElementById("diagram-customer"), function (customer) {
    entityId.value = "";
    // Si se eligió cliente directamente, autorrellena su provincia (sin resetear).
    const province = customerProvince.get(customer);
    if (province) {
      provinceControl.selectItem(province, { silent: true });
    }
    siteControl.setItems(customer.sedes || [], "Selecciona una sede");
  });
  const provinceControl = createSearchSelect(document.getElementById("diagram-province"), function (province) {
    entityId.value = "";
    customerControl.setItems(province.clientes || [], "Selecciona un cliente");
    siteControl.setItems([], "Selecciona primero un cliente");
  });

  provinceControl.setItems(catalog, "Selecciona una provincia");
  customerControl.setItems(allCustomers, "Selecciona o busca un cliente");

  function selectByEntityId(targetId) {
    if (!targetId || !catalog.length) {
      return false;
    }
    for (const province of catalog) {
      for (const customer of province.clientes || []) {
        for (const site of customer.sedes || []) {
          if (String(site.id) !== targetId) {
            continue;
          }
          provinceControl.setItems(catalog, "Selecciona una provincia");
          provinceControl.selectItem(province, { silent: true });
          customerControl.setItems(province.clientes || [], "Selecciona un cliente");
          customerControl.selectItem(customer, { silent: true });
          siteControl.setItems(customer.sedes || [], "Selecciona una sede");
          siteControl.selectItem(site);
          return true;
        }
      }
    }
    return false;
  }

  if (selectedEntityId) {
    if (!selectByEntityId(selectedEntityId)) {
      entityId.value = selectedEntityId;
    }
  }

  if (form) {
    form.addEventListener("submit", function (event) {
      if (!entityId.value) {
        event.preventDefault();
        window.alert("Selecciona una sede antes de consultar.");
      }
    });
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest(".search-select")) {
      document.querySelectorAll(".search-select.open").forEach(function (element) {
        element.classList.remove("open");
      });
    }
  });
})();
