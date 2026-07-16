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

          // Recorre las filas de categoría "switch" EN ORDEN de aparición y
          // devuelve un array [{ports}] con el nº de puertos de cada switch.
          // Solo los 2 primeros importan para el anclaje (telefonía/datos).
          function switchList() {
            const list = [];
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
              list.push({ ports: switchPortCount(modelo) });
            });
            return list;
          }

          // Estado de switches derivado de switchList(): count y puertos del
          // switch de telefonía (1º) y de datos (2º).
          function currentSwitchState() {
            const list = switchList();
            const count = list.length;
            return {
              count: count,
              telPorts: count >= 1 ? list[0].ports : 0,
              datPorts: count >= 2 ? list[1].ports : 0,
            };
          }

          // Recorre las filas y devuelve el mayor switchPortCount de los
          // switches presentes, o 0 si no hay ningún switch. Compat con el
          // esquema previo (usado en el caso de 0/1 switch).
          function currentSwitchPorts() {
            const list = switchList();
            let max = 0;
            list.forEach(function (sw) {
              if (sw.ports > max) {
                max = sw.ports;
              }
            });
            return max;
          }

          function optionHtml(value, label, selectedValue) {
            return `<option value="${value}"${selectedValue === value ? " selected" : ""}>${label}</option>`;
          }

          // Genera el HTML de <option> del select de puerto según el estado de
          // switches:
          //   0 switches → Auto + ETH3/ETH4/ETH5.
          //   1 switch   → Auto + ETH1..ETHn (sin prefijo).
          //   2+ switches → Auto + optgroup Telefonía (TEL-ETH1..) + optgroup
          //                 Datos (DAT-ETH1..).
          // excludeSwitch: 1 o 2 para NO ofrecer ese switch (si la fila ES ese
          // switch, no puede conectarse a sí mismo). Router (hAP) SIEMPRE presente.
          function puertoOptionsHtml(selectedValue, state, excludeSwitch) {
            const options = ['<option value="">Auto</option>'];
            const routerPorts = ["ETH3", "ETH4", "ETH5"]
              .map(function (v) { return optionHtml(v, v, selectedValue); }).join("");
            options.push(`<optgroup label="Router principal (hAP)">${routerPorts}</optgroup>`);
            if (state.count >= 1 && excludeSwitch !== 1) {
              const tel = [];
              for (let i = 1; i <= state.telPorts; i += 1) {
                tel.push(optionHtml("TEL-ETH" + i, "ETH" + i, selectedValue));
              }
              const label = state.count >= 2 ? "Switch 1 · Telefonía" : "Switch";
              options.push(`<optgroup label="${label}">${tel.join("")}</optgroup>`);
            }
            if (state.count >= 2 && excludeSwitch !== 2) {
              const dat = [];
              for (let i = 1; i <= state.datPorts; i += 1) {
                dat.push(optionHtml("DAT-ETH" + i, "ETH" + i, selectedValue));
              }
              options.push(`<optgroup label="Switch 2 · Datos">${dat.join("")}</optgroup>`);
            }
            return options.join("");
          }

          // Re-genera las opciones de puerto de TODAS las filas de dispositivo,
          // preservando el valor elegido si sigue siendo válido (o "Auto"), y
          // notifica a terminales vía window + CustomEvent.
          function refreshPortOptions() {
            const state = currentSwitchState();
            let switchSeen = 0;
            deviceRows.querySelectorAll(".device-row").forEach(function (row) {
              const cat = row.querySelector('[data-field="category"]');
              // Índice del switch de esta fila (1 o 2) para excluirlo de su propio
              // desplegable; las filas no-switch reciben todas las opciones.
              let excludeSwitch = null;
              if (cat && cat.value === "switch") {
                switchSeen += 1;
                if (switchSeen <= 2) excludeSwitch = switchSeen;
              }
              const puertoField = row.querySelector('[data-field="puerto"]');
              if (!puertoField) {
                return;
              }
              const previous = puertoField.value;
              puertoField.innerHTML = puertoOptionsHtml(previous, state, excludeSwitch);
              // Si el valor previo ya no existe entre las opciones, vuelve a Auto.
              if (puertoField.value !== previous) {
                puertoField.value = "";
              }
            });
            // Compat: número de puertos "máximo" (0/1 switch lo usan tal cual).
            window.__DRAWIO_SWITCH_PORTS = state.count >= 2 ? state.telPorts : currentSwitchPorts();
            // Estado completo agrupado por switch para 2+ switches.
            window.__DRAWIO_SWITCHES = {
              count: state.count,
              telPorts: state.telPorts,
              datPorts: state.datPorts,
            };
            document.dispatchEvent(
              new CustomEvent("drawio:switch-ports-changed", {
                detail: {
                  count: state.count,
                  telPorts: state.telPorts,
                  datPorts: state.datPorts,
                },
              })
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
              const pisoField = row.querySelector('[data-field="piso"]');
              const piso = pisoField ? pisoField.value : "";
              payload.push({
                category: categoryId,
                tipo: category.tipo,
                modelo: modelo,
                cantidad: cantidad,
                propiedad: propiedad,
                puerto: puerto,
                piso: piso,
              });
            });
            devicesJson.value = JSON.stringify(payload);
            updateSwitchTelefoniaVisibility();
            updateFloorVisibility();
          }

          function numPisos() {
            const inp = document.getElementById("num-pisos");
            let n = inp ? parseInt(inp.value, 10) : 2;
            if (!(n >= 1)) n = 2;
            return Math.min(n, 20);
          }

          function floorOptionsHtml(selected) {
            const opts = ['<option value="">— sin piso —</option>'];
            const n = numPisos();
            for (let i = 1; i <= n; i += 1) {
              opts.push('<option value="' + i + '"' + (selected === String(i) ? " selected" : "") + ">Piso " + i + "</option>");
            }
            return opts.join("");
          }

          function updateFloorVisibility() {
            // Con el tick activo, el desplegable de piso aparece en TODAS las filas
            // (switches y dispositivos). También muestra/oculta el input Nº de pisos.
            const cb = document.getElementById("tiene-pisos");
            const tienePisos = cb ? cb.checked : false;
            const wrap = document.getElementById("num-pisos-wrap");
            if (wrap) wrap.style.display = tienePisos ? "" : "none";
            const rpWrap = document.getElementById("router-piso-wrap");
            if (rpWrap) rpWrap.style.display = tienePisos ? "" : "none";
            deviceRows.querySelectorAll(".device-row").forEach(function (row) {
              const floor = row.querySelector(".device-floor");
              if (!floor) return;
              const sel = floor.querySelector('[data-field="piso"]');
              if (tienePisos) {
                floor.style.display = "";
                // Regenera opciones Piso 1..N preservando el valor si sigue válido.
                if (sel) {
                  const prev = sel.value;
                  sel.innerHTML = floorOptionsHtml(prev);
                  if (sel.value !== prev) sel.value = "";
                }
              } else {
                floor.style.display = "none";
                if (sel) sel.value = "";
              }
            });
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
              <label class="row-field"><span class="field-mobile-label">Puerto</span><select data-field="puerto" aria-label="Puerto ETH">${puertoOptionsHtml(values.puerto, currentSwitchState())}</select></label>
              <button type="button" class="remove-device" title="Eliminar dispositivo" aria-label="Eliminar dispositivo">×</button>
              <label class="row-field device-floor" style="grid-column:1/-1;display:none"><span class="field-mobile-label">Piso</span><select data-field="piso" aria-label="Piso">${floorOptionsHtml(values.piso)}</select></label>`;
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
          const tienePisosCheckbox = document.getElementById("tiene-pisos");
          if (tienePisosCheckbox) {
            tienePisosCheckbox.addEventListener("change", function () {
              updateFloorVisibility();
              syncDeviceRows();
              document.dispatchEvent(new CustomEvent("drawio:pisos-changed"));
            });
          }
          const numPisosInput = document.getElementById("num-pisos");
          if (numPisosInput) {
            numPisosInput.addEventListener("change", function () {
              updateFloorVisibility();
              syncDeviceRows();
              document.dispatchEvent(new CustomEvent("drawio:pisos-changed"));
            });
            numPisosInput.addEventListener("input", updateFloorVisibility);
          }
          updateSwitchTelefoniaVisibility();
          updateFloorVisibility();
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
