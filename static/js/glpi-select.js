(function () {
  const glpiCustomers = window.__DRAWIO_PAGE_CONFIG.glpiCustomers || [];
  const provinceElement = document.getElementById("glpi-province");
  if (!provinceElement || !glpiCustomers.length) {
    return;
  }
          const fields = {
            cliente: document.getElementById("cliente"),
            cif: document.getElementById("cif"),
            sede: document.getElementById("sede"),
            direccion: document.getElementById("direccion")
          };
          const glpiEntityId = document.getElementById("glpi-entity-id");

          function createSearchSelect(element, onSelect) {
            let items = [];
            let selected = null;
            element.innerHTML = `
              <button type="button" class="search-select-trigger">
                <span>${element.dataset.placeholder}</span><span class="search-select-arrow">▾</span>
              </button>
              <div class="search-select-menu">
                <input type="search" class="search-select-filter" placeholder="Buscar...">
                <div class="search-select-options"></div>
              </div>`;
            const trigger = element.querySelector(".search-select-trigger");
            const label = trigger.querySelector("span");
            const filter = element.querySelector(".search-select-filter");
            const options = element.querySelector(".search-select-options");

            function render(query = "") {
              const normalized = query.toLocaleLowerCase("es");
              options.innerHTML = "";
              items
                .filter(item => item.nombre.toLocaleLowerCase("es").includes(normalized))
                .forEach(item => {
                  const button = document.createElement("button");
                  button.type = "button";
                  button.className = "search-select-option";
                  button.textContent = item.nombre;
                  button.addEventListener("click", function () {
                    selected = item;
                    label.textContent = item.nombre;
                    element.classList.remove("open");
                    filter.value = "";
                    onSelect(item);
                  });
                  options.appendChild(button);
                });
              if (!options.children.length) {
                options.innerHTML = '<div class="search-select-empty">Sin resultados</div>';
              }
            }

            trigger.addEventListener("click", function () {
              if (element.classList.contains("disabled")) return;
              document.querySelectorAll(".search-select.open").forEach(other => {
                if (other !== element) other.classList.remove("open");
              });
              element.classList.toggle("open");
              if (element.classList.contains("open")) {
                render();
                filter.focus();
              }
            });
            filter.addEventListener("input", () => render(filter.value));

            return {
              setItems(newItems, placeholder) {
                items = newItems;
                selected = null;
                label.textContent = placeholder;
                element.dataset.placeholder = placeholder;
                element.classList.toggle("disabled", !newItems.length);
                render();
              },
              getSelected() {
                return selected;
              },
              selectItem(item) {
                if (!item) {
                  return;
                }
                selected = item;
                label.textContent = item.nombre;
                element.classList.remove("open");
                filter.value = "";
                onSelect(item);
              },
            };
          }

          let provinceControl;
          let customerControl;
          let siteControl;

          siteControl = createSearchSelect(document.getElementById("glpi-site"), function (site) {
            const customer = customerControl.getSelected();
            fields.sede.value = site.nombre || "Sede Principal";
            fields.direccion.value = site.direccion || customer.direccion || "";
            glpiEntityId.value = String(site.id);
            const source = document.getElementById("address-source");
            source.textContent = site.direccion_guardada
              ? "Dirección exacta guardada anteriormente por un técnico. Puedes corregirla si ha cambiado."
              : "Dirección procedente de GLPI. Complétala con la calle exacta; se guardará al generar.";
          });

          customerControl = createSearchSelect(document.getElementById("glpi-customer"), function (customer) {
            fields.cliente.value = customer.nombre || "";
            fields.cif.value = customer.cif || "";
            fields.direccion.value = customer.direccion || "";
            glpiEntityId.value = "";
            siteControl.setItems(customer.sedes, "Selecciona una sede");
          });

          provinceControl = createSearchSelect(document.getElementById("glpi-province"), function (province) {
            glpiEntityId.value = "";
            customerControl.setItems(province.clientes, "Selecciona un cliente");
            siteControl.setItems([], "Selecciona primero un cliente");
          });

          provinceControl.setItems(glpiCustomers, "Selecciona una provincia");

          window.__drawioGlpiSelectByEntityId = function (entityId) {
            if (!entityId || !glpiCustomers.length) {
              return false;
            }
            const targetId = String(entityId);
            for (const province of glpiCustomers) {
              for (const customer of province.clientes || []) {
                for (const site of customer.sedes || []) {
                  if (String(site.id) !== targetId) {
                    continue;
                  }
                  provinceControl.selectItem(province);
                  customerControl.selectItem(customer);
                  siteControl.selectItem(site);
                  fields.cliente.value = customer.nombre || "";
                  fields.cif.value = customer.cif || "";
                  fields.sede.value = site.nombre || "";
                  glpiEntityId.value = targetId;
                  return true;
                }
              }
            }
            return false;
          };

          window.__drawioGlpiMatch = function (imported) {
            if (!imported || !glpiCustomers.length) {
              return { matched: false, message: "" };
            }
            if (imported.glpi_entity_id && window.__drawioGlpiSelectByEntityId(imported.glpi_entity_id)) {
              if (imported.cliente) fields.cliente.value = imported.cliente;
              if (imported.cif) fields.cif.value = imported.cif;
              if (imported.sede) fields.sede.value = imported.sede;
              if (imported.direccion) fields.direccion.value = imported.direccion;
              glpiEntityId.value = String(imported.glpi_entity_id);
              const source = document.getElementById("address-source");
              if (source && imported.direccion) {
                source.textContent = "Dirección revisada con GLPI y la oferta. Puedes corregirla si ha cambiado.";
              }
              return {
                matched: true,
                message: imported.glpi_message || `GLPI: ${imported.cliente} / ${imported.sede}`,
              };
            }

            const normalize = function (value) {
              return String(value || "")
                .toLocaleLowerCase("es")
                .normalize("NFD")
                .replace(/[\u0300-\u036f]/g, "")
                .replace(/\s+/g, " ")
                .trim();
            };
            const targetCif = (imported.cif || "").replace(/\s+/g, "").toUpperCase();
            const targetClient = normalize(imported.cliente);
            const targetSite = normalize(imported.sede);
            const targetAddress = normalize(imported.direccion);

            function siteScore(site) {
              let score = 0;
              const siteName = normalize(site.nombre);
              const siteAddress = normalize(site.direccion);
              if (targetSite && (siteName.includes(targetSite) || targetSite.includes(siteName))) {
                score += 20;
              }
              targetAddress.split(/[\s,.-]+/).filter(function (token) {
                return token.length > 3;
              }).forEach(function (token) {
                if (siteAddress.includes(token) || siteName.includes(token)) {
                  score += 2;
                }
              });
              return score;
            }

            for (const province of glpiCustomers) {
              for (const customer of province.clientes || []) {
                const customerCif = (customer.cif || "").replace(/\s+/g, "").toUpperCase();
                const customerName = normalize(customer.nombre);
                const cifMatch = targetCif && customerCif && targetCif === customerCif;
                const nameMatch = targetClient && customerName && (
                  customerName.includes(targetClient) || targetClient.includes(customerName)
                );
                if (!cifMatch && !nameMatch) {
                  continue;
                }

                const sites = customer.sedes || [];
                let bestSite = sites[0] || null;
                let bestScore = -1;
                sites.forEach(function (site) {
                  const score = siteScore(site);
                  if (score > bestScore) {
                    bestScore = score;
                    bestSite = site;
                  }
                });

                provinceControl.selectItem(province);
                customerControl.selectItem(customer);
                if (bestSite) {
                  siteControl.selectItem(bestSite);
                  if (imported.direccion) {
                    fields.direccion.value = imported.direccion;
                  }
                } else {
                  fields.cliente.value = customer.nombre || imported.cliente || "";
                  fields.cif.value = customer.cif || imported.cif || "";
                  fields.sede.value = imported.sede || "";
                  fields.direccion.value = imported.direccion || customer.direccion || "";
                  glpiEntityId.value = "";
                }

                return {
                  matched: true,
                  message: bestSite
                    ? `GLPI: ${customer.nombre} / ${bestSite.nombre}`
                    : `GLPI: cliente ${customer.nombre} encontrado. Selecciona la sede manualmente.`,
                };
              }
            }
            return { matched: false, message: "No se ha encontrado el cliente en GLPI. Rellena la sede manualmente." };
          };

          document.addEventListener("click", function (event) {
            if (!event.target.closest(".search-select")) {
              document.querySelectorAll(".search-select.open").forEach(element => element.classList.remove("open"));
            }
          });
})();
