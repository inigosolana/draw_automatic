(function () {
          const deviceCatalog = window.__DRAWIO_PAGE_CONFIG.deviceCatalog || [];
          const deviceRows = document.getElementById("device-rows");
          const devicesJson = document.getElementById("devices-json");

          function escapeAttribute(value) {
            return String(value || "")
              .replaceAll("&", "&amp;")
              .replaceAll('"', "&quot;")
              .replaceAll("<", "&lt;")
              .replaceAll(">", "&gt;");
          }

          // Deriva el nº de puertos de un switch a partir del nombre del modelo.
          // Patrones (case-insensitive) + casos especiales. Devuelve 8 por
          // defecto si no detecta un número válido (2..48).
          function switchPortCount(modelo) {
            const name = String(modelo || "");
            if (/108GL/i.test(name) || /DGS[\s_-]*108/i.test(name)) {
              return 8;
            }
            const patterns = [
              /(\d+)\s*P\b/i,
              /(\d+)[_ ]?PORTS?\b/i,
              /(\d+)\s*-?\s*puertos/i,
            ];
            for (let i = 0; i < patterns.length; i += 1) {
              const match = name.match(patterns[i]);
              if (match) {
                const n = parseInt(match[1], 10);
                if (n >= 2 && n <= 48) {
                  return n;
                }
              }
            }
            return 8;
          }

          // Recorre las filas y devuelve el mayor switchPortCount de los
          // switches presentes, o 0 si no hay ningún switch.
          function currentSwitchPorts() {
            let max = 0;
            deviceRows.querySelectorAll(".device-row").forEach(function (row) {
              const categoryField = row.querySelector('[data-field="category"]');
              if (!categoryField || categoryField.value !== "switch") {
                return;
              }
              const category = categoryById(categoryField.value);
              const modelField = row.querySelector('[data-field="model"]');
              const customField = row.querySelector('[data-field="custom-model"]');
              const modelo = category.custom
                ? (customField ? customField.value.trim() : "")
                : (modelField ? modelField.value.trim() : "");
              const ports = switchPortCount(modelo);
              if (ports > max) {
                max = ports;
              }
            });
            return max;
          }

          // Genera el HTML de <option> del select de puerto según haya o no
          // switch. Con switch: Auto + ETH1..ETHn. Sin switch: Auto + ETH3/4/5.
          function puertoOptionsHtml(selectedValue, switchPorts) {
            const values = [];
            if (switchPorts > 0) {
              for (let i = 1; i <= switchPorts; i += 1) {
                values.push("ETH" + i);
              }
            } else {
              values.push("ETH3", "ETH4", "ETH5");
            }
            const options = ['<option value="">Auto</option>'];
            values.forEach(function (value) {
              options.push(
                `<option value="${value}"${selectedValue === value ? " selected" : ""}>${value}</option>`
              );
            });
            return options.join("");
          }

          // Re-genera las opciones de puerto de TODAS las filas de dispositivo,
          // preservando el valor elegido si sigue siendo válido (o "Auto"), y
          // notifica a terminales vía window + CustomEvent.
          function refreshPortOptions() {
            const switchPorts = currentSwitchPorts();
            deviceRows.querySelectorAll(".device-row").forEach(function (row) {
              const puertoField = row.querySelector('[data-field="puerto"]');
              if (!puertoField) {
                return;
              }
              const previous = puertoField.value;
              puertoField.innerHTML = puertoOptionsHtml(previous, switchPorts);
              // Si el valor previo ya no existe entre las opciones, vuelve a Auto.
              if (puertoField.value !== previous) {
                puertoField.value = "";
              }
            });
            window.__DRAWIO_SWITCH_PORTS = switchPorts;
            document.dispatchEvent(
              new CustomEvent("drawio:switch-ports-changed", { detail: { ports: switchPorts } })
            );
          }

          function categoryById(categoryId) {
            return deviceCatalog.find(function (category) {
              return category.id === categoryId;
            }) || deviceCatalog[deviceCatalog.length - 1] || { models: [], custom: true };
          }

          function modelOptionsForCategory(categoryId, selectedModel) {
            const category = categoryById(categoryId);
            if (category.custom) {
              return "";
            }
            const options = ['<option value="">Selecciona modelo</option>'];
            (category.models || []).forEach(function (model) {
              options.push(
                `<option value="${escapeAttribute(model)}"${selectedModel === model ? " selected" : ""}>${escapeAttribute(model)}</option>`
              );
            });
            return options.join("");
          }

          function brandOf(model) {
            const m = (model || "").toLowerCase();
            if (/fanvil/.test(m)) return { cls: "b-fanvil", txt: "F" };
            if (/grandstream|gwn|gxp|grp/.test(m)) return { cls: "b-grandstream", txt: "G" };
            if (/tp-?link|deco/.test(m)) return { cls: "b-tplink", txt: "TP" };
            if (/d-?link|dgs/.test(m)) return { cls: "b-dlink", txt: "DL" };
            if (/ruijie/.test(m)) return { cls: "b-ruijie", txt: "RJ" };
            if (/tenda/.test(m)) return { cls: "b-tenda", txt: "TD" };
            if (/mikrotik|microtik|hap|chateau/.test(m)) return { cls: "b-mikrotik", txt: "MT" };
            if (/firebox|watchguard/.test(m)) return { cls: "b-generic", txt: "FW" };
            return null;
          }
          function setDeviceBrand(row, modelo) {
            const badge = row.querySelector("[data-brand]");
            if (!badge) return;
            const br = brandOf(modelo);
            badge.className = "brand-badge " + (br ? br.cls : "b-empty");
            badge.textContent = br ? br.txt : "";
          }

          function syncDeviceRows() {
            // Recalcula las opciones de puerto (dispositivos + terminales) antes
            // de recolectar el payload, por si cambió algún switch.
            refreshPortOptions();
            const payload = [];
            const usados = new Set();
            deviceRows.querySelectorAll(".device-row").forEach(function (row) {
              const categoryId = row.querySelector('[data-field="category"]').value;
              const category = categoryById(categoryId);
              const modelField = row.querySelector('[data-field="model"]');
              const customField = row.querySelector('[data-field="custom-model"]');
              const modelo = category.custom
                ? (customField ? customField.value.trim() : "")
                : modelField.value.trim();
              setDeviceBrand(row, modelo);
              const cantidad = Math.max(1, parseInt(row.querySelector('[data-field="quantity"]').value || "1", 10));
              const propiedad = row.querySelector('[data-field="ownership"]').value;
              // Detectar puertos ETH duplicados (ignorando '' = Auto). Marca la fila
              // en conflicto para dar feedback al usuario; no se altera el payload.
              const puertoField = row.querySelector('[data-field="puerto"]');
              const puerto = puertoField ? puertoField.value : "";
              if (puerto && usados.has(puerto)) {
                row.classList.add("dup-port");
              } else {
                row.classList.remove("dup-port");
                if (puerto) {
                  usados.add(puerto);
                }
              }
              if (!modelo) return;
              payload.push({
                category: categoryId,
                tipo: category.tipo,
                modelo: modelo,
                cantidad: cantidad,
                propiedad: propiedad,
                puerto: puerto,
              });
            });
            devicesJson.value = JSON.stringify(payload);
            updateSwitchTelefoniaVisibility();
          }

          function hasDuplicatePorts() {
            return deviceRows.querySelectorAll(".device-row.dup-port").length > 0;
          }

          function updateSwitchTelefoniaVisibility() {
            const wrap = document.getElementById("switch-telefonia-wrap");
            const hint = document.getElementById("switch-telefonia-hint");
            const checkbox = document.getElementById("switch-telefonia");
            if (!wrap) {
              return;
            }
            const hasSwitch = Array.from(deviceRows.querySelectorAll('[data-field="category"]')).some(function (field) {
              return field.value === "switch";
            });
            wrap.hidden = !hasSwitch;
            if (hint) {
              hint.hidden = !hasSwitch || !checkbox || checkbox.checked;
            }
          }

          function updateModelField(row) {
            const categoryId = row.querySelector('[data-field="category"]').value;
            const category = categoryById(categoryId);
            const modelSelect = row.querySelector('[data-field="model"]');
            const customInput = row.querySelector('[data-field="custom-model"]');
            if (category.custom) {
              modelSelect.hidden = true;
              modelSelect.disabled = true;
              customInput.hidden = false;
              customInput.disabled = false;
            } else {
              modelSelect.hidden = false;
              modelSelect.disabled = false;
              customInput.hidden = true;
              customInput.disabled = true;
              modelSelect.innerHTML = modelOptionsForCategory(categoryId, modelSelect.value);
            }
            syncDeviceRows();
          }

          function addDeviceRow(values) {
            values = values || {};
            const row = document.createElement("div");
            row.className = "device-row";
            const categoryOptions = deviceCatalog.map(function (category) {
              return `<option value="${category.id}"${values.category === category.id ? " selected" : ""}>${escapeAttribute(category.label)}</option>`;
            }).join("");
            row.innerHTML = `
              <label class="row-field">
                <span class="field-mobile-label">Tipo</span>
                <select data-field="category" aria-label="Tipo de dispositivo">${categoryOptions}</select>
              </label>
              <div class="row-field device-model-field">
                <span class="field-mobile-label">Modelo</span>
                <span class="model-with-brand"><span class="brand-badge b-empty" data-brand aria-hidden="true"></span><select data-field="model" aria-label="Modelo de dispositivo"></select></span>
                <input data-field="custom-model" type="text" placeholder="Modelo personalizado" value="${escapeAttribute(values.modelo)}" aria-label="Modelo personalizado" hidden disabled>
              </div>
              <label class="row-field">
                <span class="field-mobile-label">Cantidad</span>
                <input data-field="quantity" type="number" min="1" value="${escapeAttribute(values.cantidad || 1)}" aria-label="Cantidad">
              </label>
              <label class="row-field">
                <span class="field-mobile-label">Propiedad</span>
                <select data-field="ownership" aria-label="Propiedad">
                  <option value="propio"${values.propiedad !== "ajeno" ? " selected" : ""}>Propio</option>
                  <option value="ajeno"${values.propiedad === "ajeno" ? " selected" : ""}>Ajeno</option>
                </select>
              </label>
              <label class="row-field"><span class="field-mobile-label">Puerto</span><select data-field="puerto" aria-label="Puerto ETH"><option value="">Auto</option><option value="ETH3"${values.puerto === "ETH3" ? " selected" : ""}>ETH3</option><option value="ETH4"${values.puerto === "ETH4" ? " selected" : ""}>ETH4</option><option value="ETH5"${values.puerto === "ETH5" ? " selected" : ""}>ETH5</option></select></label>
              <button type="button" class="remove-device" title="Eliminar dispositivo" aria-label="Eliminar dispositivo">×</button>`;
            const categoryField = row.querySelector('[data-field="category"]');
            if (values.category) {
              categoryField.value = values.category;
            }
            const modelField = row.querySelector('[data-field="model"]');
            if (values.modelo && !categoryById(categoryField.value).custom) {
              modelField.innerHTML = modelOptionsForCategory(categoryField.value, values.modelo);
            }
            categoryField.addEventListener("change", function () {
              modelField.value = "";
              row.querySelector('[data-field="custom-model"]').value = "";
              updateModelField(row);
            });
            row.querySelectorAll("input, select").forEach(function (field) {
              field.addEventListener("input", syncDeviceRows);
              field.addEventListener("change", syncDeviceRows);
            });
            row.querySelector(".remove-device").addEventListener("click", function () {
              row.remove();
              syncDeviceRows();
            });
            deviceRows.appendChild(row);
            updateModelField(row);
            if (values.modelo && categoryById(categoryField.value).custom) {
              row.querySelector('[data-field="custom-model"]').value = values.modelo;
            }
            syncDeviceRows();
          }

          function loadExistingDeviceRows() {
            let items = [];
            try {
              items = JSON.parse(devicesJson.value || "[]");
            } catch (error) {
              items = [];
            }
            if (!items.length) {
              addDeviceRow({ category: "switch" });
              return;
            }
            items.forEach(function (item) {
              addDeviceRow(item);
            });
            syncDeviceRows();
          }

          document.getElementById("add-device").addEventListener("click", function () {
            addDeviceRow({ category: "switch" });
            deviceRows.lastElementChild.querySelector('[data-field="category"]').focus();
          });
          document.querySelector(".creation-form").addEventListener("submit", function (event) {
            syncDeviceRows();
            if (hasDuplicatePorts()) {
              event.preventDefault();
              window.alert("Hay puertos ETH asignados al mismo valor en varios dispositivos. Corrige los puertos duplicados (marcados) o dejalos en Auto.");
            }
          });
          loadExistingDeviceRows();
          const switchTelefoniaCheckbox = document.getElementById("switch-telefonia");
          if (switchTelefoniaCheckbox) {
            switchTelefoniaCheckbox.addEventListener("change", updateSwitchTelefoniaVisibility);
          }
          updateSwitchTelefoniaVisibility();
          window.__drawioDevices = {
            rows: deviceRows,
            addRow: addDeviceRow,
            sync: syncDeviceRows,
            clear: function () {
              deviceRows.innerHTML = "";
              devicesJson.value = "[]";
            },
          };
})();
