(function () {
  const configElement = document.getElementById("upload-glpi-config");
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
  const siteDiagramsUrl = config.siteDiagramsUrl || "";
  const createSearchSelect = window.__drawioCreateSearchSelect;
  const existingPanel = document.getElementById("upload-existing-panel");
  const existingTitle = document.getElementById("upload-existing-title");
  const existingBody = document.getElementById("upload-existing-body");
  const addressPanel = document.getElementById("upload-glpi-address");
  const addressInput = document.getElementById("upload-direccion");
  const addressHint = document.getElementById("upload-glpi-address-hint");
  const addressReference = document.getElementById("upload-glpi-address-reference");
  const addressOriginal = document.getElementById("upload-glpi-address-original");

  function glpiOriginalStreet(siteOrCustomer) {
    if (!siteOrCustomer) {
      return "";
    }
    return siteOrCustomer.direccion_glpi || siteOrCustomer.direccion || "";
  }

  function effectiveStreet(site, customer) {
    if (site) {
      return site.direccion || customer.direccion || "";
    }
    return customer ? customer.direccion || "" : "";
  }

  function clearGlpiAddress() {
    if (!addressPanel || !addressInput) {
      return;
    }
    addressInput.value = "";
    if (addressOriginal) {
      addressOriginal.textContent = "—";
    }
    if (addressReference) {
      addressReference.hidden = true;
    }
    addressPanel.hidden = true;
  }

  function showGlpiAddress(site, customer, context) {
    if (!addressPanel || !addressInput) {
      return;
    }

    const original = glpiOriginalStreet(site || customer);
    const current = effectiveStreet(site, customer);

    if (context === "cliente") {
      addressInput.value = current;
      if (addressReference && addressOriginal) {
        if (original) {
          addressOriginal.textContent = original;
          addressReference.hidden = false;
        } else {
          addressReference.hidden = true;
        }
      }
      if (addressHint) {
        addressHint.textContent =
          "Direccion del cliente en GLPI. Al elegir la sede podras corregir la calle concreta.";
      }
      addressPanel.hidden = false;
      return;
    }

    addressInput.value = current;
    if (addressReference && addressOriginal) {
      if (original) {
        addressOriginal.textContent = original;
        addressReference.hidden = false;
      } else {
        addressReference.hidden = true;
      }
    }
    if (addressHint) {
      if (site && site.direccion_guardada) {
        addressHint.textContent =
          "Hay una calle guardada por un tecnico. Si la cambias, se actualizara en GLPI al subir el draw.";
      } else {
        addressHint.textContent =
          "Revisa la calle antes de subir. Si la corriges, se actualizara en GLPI y quedara guardada para esta sede.";
      }
    }
    addressPanel.hidden = false;
  }

  function clearExistingDiagrams() {
    if (!existingPanel || !existingBody) {
      return;
    }
    existingBody.innerHTML = "";
    existingPanel.hidden = true;
  }

  async function loadExistingDiagrams(entityId) {
    if (!existingPanel || !existingBody || !siteDiagramsUrl || !entityId) {
      clearExistingDiagrams();
      return;
    }

    existingPanel.hidden = false;
    existingBody.innerHTML = '<tr><td colspan="4">Cargando diagramas...</td></tr>';

    try {
      const response = await fetch(
        siteDiagramsUrl + "?entity_id=" + encodeURIComponent(entityId),
        { credentials: "same-origin" }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "No se pudieron cargar los diagramas.");
      }

      const diagrams = payload.diagrams || [];
      if (!diagrams.length) {
        clearExistingDiagrams();
        return;
      }

      if (existingTitle) {
        const latest = diagrams[0];
        if (diagrams.length === 1) {
          existingTitle.textContent =
            "Ya hay un draw en esta sede (fecha " + latest.created_label + ")";
        } else {
          existingTitle.textContent =
            "Ya hay " + diagrams.length + " draws en esta sede (ultimo: " + latest.created_label + ")";
        }
      }

      existingBody.innerHTML = "";
      diagrams.forEach(function (diagram) {
        const row = document.createElement("tr");
        row.innerHTML =
          '<td data-label="Nombre">' + escapeHtml(diagram.name || "Diagrama") + "</td>" +
          '<td data-label="Fecha">' + escapeHtml(diagram.created_label || "—") + "</td>" +
          '<td data-label="Tecnico">' + escapeHtml(diagram.technician || "—") + "</td>" +
          '<td data-label="">' +
          (diagram.preview_url
            ? '<a class="button secondary quiet" href="' +
              escapeHtml(diagram.preview_url) +
              '">Previsualizar</a>'
            : diagram.url
            ? '<a class="button secondary quiet" href="' +
              escapeHtml(diagram.url) +
              '" target="_blank" rel="noopener">Abrir en GLPI</a>'
            : "") +
          "</td>";
        existingBody.appendChild(row);
      });
      existingPanel.hidden = false;
    } catch (error) {
      existingBody.innerHTML =
        '<tr><td colspan="4">' + escapeHtml(error.message || "Error al consultar diagramas.") + "</td></tr>";
      existingPanel.hidden = false;
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  let selectedCustomer = null;

  const siteControl = createSearchSelect(document.getElementById("upload-site"), function (site) {
    document.getElementById("upload-entity-id").value = site.id;
    document.getElementById("upload-site-name").value = site.nombre;
    showGlpiAddress(site, selectedCustomer, "sede");
    loadExistingDiagrams(site.id);
  });
  const customerControl = createSearchSelect(document.getElementById("upload-customer"), function (customer) {
    selectedCustomer = customer;
    document.getElementById("upload-client-name").value = customer.nombre;
    document.getElementById("upload-entity-id").value = "";
    document.getElementById("upload-site-name").value = "";
    siteControl.setItems(customer.sedes, "Selecciona una sede");
    showGlpiAddress(null, customer, "cliente");
    clearExistingDiagrams();
  });
  const provinceControl = createSearchSelect(document.getElementById("upload-province"), function (province) {
    selectedCustomer = null;
    customerControl.setItems(province.clientes, "Selecciona un cliente");
    siteControl.setItems([], "Selecciona primero un cliente");
    document.getElementById("upload-entity-id").value = "";
    document.getElementById("upload-client-name").value = "";
    document.getElementById("upload-site-name").value = "";
    clearGlpiAddress();
    clearExistingDiagrams();
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

// Estado "trabajando" en el boton de subir (feedback + evita doble clic).
(function () {
  const form = document.getElementById("upload-draw-form");
  if (!form) return;
  form.addEventListener("submit", function () {
    const btn = form.querySelector('button[type="submit"]');
    if (btn && !btn.dataset.busy) {
      btn.dataset.busy = "1";
      setTimeout(function () {
        btn.disabled = true;
        btn.classList.add("is-busy");
        btn.innerHTML = '<span class="btn-spinner" aria-hidden="true"></span> Subiendo…';
      }, 0);
    }
  });
})();
