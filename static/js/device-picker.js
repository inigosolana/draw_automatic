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
            const payload = [];
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
              if (!modelo) return;
              payload.push({
                category: categoryId,
                tipo: category.tipo,
                modelo: modelo,
                cantidad: cantidad,
                propiedad: propiedad,
              });
            });
            devicesJson.value = JSON.stringify(payload);
            updateSwitchTelefoniaVisibility();
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
          document.querySelector(".creation-form").addEventListener("submit", syncDeviceRows);
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
