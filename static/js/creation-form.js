(function () {
          const internetType = document.getElementById("internet-tipo");
          const internetVelocidad = document.getElementById("internet-velocidad");
          const internetVelocidadLabel = document.getElementById("internet-velocidad-label");
          const internetMetricLabel = document.getElementById("internet-metric-label");
          const internetProveedor = document.getElementById("internet-proveedor");
          const routerModel = document.getElementById("router-modelo");
          const ontModel = document.getElementById("ont-modelo");
          const backupModel = document.getElementById("backup-modelo");
          const backupHelp = document.getElementById("backup-help");
          const FIBER_PROVIDERS = ["AIRE", "ADAMO", "MAS MOVIL", "EUSKALTEL", "SARENET", "SARENET ORANGE"];
          const MONITORED_4G_PROVIDERS = ["Movistar", "Movistar M2M", "Vodafone", "Orange", "PTVTELECOM"];
          const FIBER_SPEEDS = ["300 MB", "600 MB", "1 GB"];
          const CAPACITY_BY_PROVIDER = {
            "Movistar": "400 GB",
            "Movistar M2M": "400 GB",
            "Vodafone": "1 TB",
            "Orange": "700 GB",
            "PTVTELECOM": "700 GB",
          };

          function providerCapacity(provider) {
            return CAPACITY_BY_PROVIDER[provider] || "";
          }

          function renderMetricOptions() {
            const is4gMonitored = internetType.value === "SOLO 4G MONITORIZADO";
            const current = internetVelocidad.value || internetVelocidad.dataset.selected || "";
            internetVelocidad.innerHTML = "";
            if (is4gMonitored) {
              internetMetricLabel.textContent = "Capacidad";
              const placeholder = document.createElement("option");
              placeholder.value = "";
              placeholder.textContent = internetProveedor.value
                ? "Sin capacidad definida"
                : "Selecciona primero un proveedor";
              internetVelocidad.appendChild(placeholder);
              const capacity = providerCapacity(internetProveedor.value);
              if (capacity) {
                const option = document.createElement("option");
                option.value = capacity;
                option.textContent = capacity;
                option.selected = current === capacity || !current;
                internetVelocidad.appendChild(option);
              }
              internetVelocidad.disabled = !internetProveedor.value;
            } else {
              internetMetricLabel.textContent = "Velocidad";
              const placeholder = document.createElement("option");
              placeholder.value = "";
              placeholder.textContent = "Selecciona una velocidad";
              internetVelocidad.appendChild(placeholder);
              FIBER_SPEEDS.forEach(function (speed) {
                const option = document.createElement("option");
                option.value = speed;
                option.textContent = speed;
                if (speed === current) {
                  option.selected = true;
                }
                internetVelocidad.appendChild(option);
              });
              internetVelocidad.disabled = false;
            }
            internetVelocidad.dataset.selected = "";
          }

          function renderProviderOptions() {
            const is4gMonitored = internetType.value === "SOLO 4G MONITORIZADO";
            const providers = is4gMonitored ? MONITORED_4G_PROVIDERS : FIBER_PROVIDERS;
            const current = internetProveedor.value || internetProveedor.dataset.selected || "";
            internetProveedor.innerHTML = '<option value="">Selecciona un proveedor</option>';
            providers.forEach(function (provider) {
              const option = document.createElement("option");
              option.value = provider;
              option.textContent = provider;
              if (provider === current) {
                option.selected = true;
              }
              internetProveedor.appendChild(option);
            });
            if (current && !providers.includes(current)) {
              internetProveedor.value = "";
            }
            internetProveedor.dataset.selected = "";
            renderMetricOptions();
          }

          function is4gMonitoredType() {
            return internetType.value === "SOLO 4G MONITORIZADO";
          }

          function updateOntSelector() {
            const is4gMonitored = is4gMonitoredType();
            ontModel.disabled = is4gMonitored;
            if (is4gMonitored) {
              ontModel.value = "";
              ontModel.options[0].textContent = "No aplica con 4G monitorizado";
            } else {
              ontModel.options[0].textContent = "Selecciona una ONT";
            }
          }

          function updateRouterSelector() {
            const is4gMonitored = is4gMonitoredType();
            const current = routerModel.value;
            if (is4gMonitored) {
              if (current && current !== "CHATEAU") {
                routerModel.dataset.lastSelection = current;
              }
              routerModel.innerHTML = '<option value="CHATEAU">CHATEAU</option>';
              routerModel.value = "CHATEAU";
              return;
            }
            const restore = current && current !== "CHATEAU"
              ? current
              : (routerModel.dataset.lastSelection || "");
            routerModel.innerHTML = [
              '<option value="">Selecciona un router</option>',
              '<option value="MikroTik hAP ac2">MikroTik hAP ac2</option>',
              '<option value="MikroTik hAP ac3">MikroTik hAP ac3</option>',
              '<option value="CHATEAU">CHATEAU</option>',
            ].join("");
            if (restore && Array.from(routerModel.options).some(function (option) { return option.value === restore; })) {
              routerModel.value = restore;
            }
          }

          function updateInternetFields() {
            renderProviderOptions();
            updateOntSelector();
            updateRouterSelector();
            updateBackupSelector();
          }

          const HAP_ROUTERS = ["MikroTik hAP ac2", "MikroTik hAP ac3"];

          function isHapRouter(model) {
            return HAP_ROUTERS.includes(model);
          }

          function updateBackupSelector() {
            const is4gMonitored = is4gMonitoredType();
            if (is4gMonitored) {
              backupModel.value = "";
              backupModel.disabled = true;
              backupModel.options[0].textContent = "No aplica con 4G monitorizado";
              backupHelp.textContent = "Con 4G monitorizado el router debe ser CHATEAU. No hay ONT ni equipo de backup externo.";
              return;
            }

            const usesBackup = internetType.value === "FIBRA + BACK UP";
            const isChateau = routerModel.value === "CHATEAU";
            const canUseExternalBackup = usesBackup && !isChateau && isHapRouter(routerModel.value);

            if (isChateau) {
              backupModel.value = "";
              backupModel.disabled = true;
              backupModel.options[0].textContent = usesBackup
                ? "Integrado en CHATEAU"
                : "No necesario con CHATEAU";
              backupHelp.textContent = usesBackup
                ? "El backup 4G está integrado en el propio CHATEAU. No se añade ningún dispositivo externo."
                : "CHATEAU incluye conectividad móvil integrada; no necesita un equipo de backup independiente.";
              return;
            }

            backupModel.disabled = !canUseExternalBackup;
            backupModel.options[0].textContent = canUseExternalBackup
              ? "Selecciona WAP LTE o TELTONIKA"
              : "Sin equipo de backup";
            if (!canUseExternalBackup) {
              backupModel.value = "";
            }
            backupHelp.textContent = canUseExternalBackup
              ? "Con hAP ac2/ac3 y Fibra + Backup selecciona WAP LTE o TELTONIKA para conectarlo a ETH2."
              : "El equipo de backup externo solo se utiliza con Fibra + Backup y MikroTik hAP ac2 o ac3.";
          }

          internetType.addEventListener("change", updateInternetFields);
          internetProveedor.addEventListener("change", renderMetricOptions);
          routerModel.addEventListener("change", updateBackupSelector);
          document.querySelector(".creation-form").addEventListener("submit", function () {
            if (internetType.value === "SOLO 4G MONITORIZADO") {
              routerModel.value = "CHATEAU";
              const capacity = providerCapacity(internetProveedor.value);
              if (capacity) {
                internetVelocidad.value = capacity;
              }
            }
          });
          updateInternetFields();

          const terminalRows = document.getElementById("terminal-rows");
          const terminalDetails = document.getElementById("terminal-details");
          const terminalEquipmentText = document.getElementById("terminal-equipment-text");
          const terminalModels = ["FANVIL V62", "FANVIL V64", "T-30", "T-31", "T-33", "T-43", "T-44", "T-73", "W71H", "W72H", "W53H", "W73H"];
          const DECT_HANDSET_MODELS = ["W71H", "W72H", "W53H", "W73H"];
          const DECT_BASE_MODELS = ["W60B", "W70B", "W80B", "YEALINK W90DM"];
          const DEFAULT_DECT_BASE = {
            "W71H": "W60B",
            "W72H": "W60B",
            "W53H": "W80B",
            "W73H": "YEALINK W90DM",
          };

          function isDectHandset(model) {
            return DECT_HANDSET_MODELS.includes(model);
          }

          function updateDectBaseField(row) {
            const model = row.querySelector('[data-field="model"]').value.trim();
            const dectField = row.querySelector('[data-field="dect-base"]');
            const showDect = isDectHandset(model);
            dectField.disabled = !showDect;
            dectField.classList.toggle("is-hidden", !showDect);
            if (showDect && !dectField.value) {
              dectField.value = DEFAULT_DECT_BASE[model] || "W60B";
            }
            if (!showDect) {
              dectField.value = "";
            }
          }

          function syncTerminalRows() {
            const detailLines = [];
            const equipmentLines = [];
            terminalRows.querySelectorAll(".terminal-row").forEach(function (row) {
              const model = row.querySelector('[data-field="model"]').value.trim();
              const dectBase = row.querySelector('[data-field="dect-base"]').value.trim();
              const extension = row.querySelector('[data-field="extension"]').value.trim();
              const serial = row.querySelector('[data-field="serial"]').value.trim();
              const mac = row.querySelector('[data-field="mac"]').value.trim();
              const ip = row.querySelector('[data-field="ip"]').value.trim();
              const ownership = row.querySelector('[data-field="ownership"]').value;
              if (!model && !extension && !serial && !mac && !ip) return;
              detailLines.push([model, extension, serial, mac, ip, ownership, dectBase].join(" | "));
              if (model) {
                const extensionText = extension ? `, extension ${extension}` : "";
                const baseText = isDectHandset(model) && dectBase ? `, base ${dectBase}` : "";
                equipmentLines.push(`1 ${model}${extensionText}${baseText} ${ownership}`);
              }
            });
            terminalDetails.value = detailLines.join("\n");
            terminalEquipmentText.value = equipmentLines.join("\n");
          }

          function escapeAttribute(value) {
            return String(value || "")
              .replaceAll("&", "&amp;")
              .replaceAll('"', "&quot;")
              .replaceAll("<", "&lt;")
              .replaceAll(">", "&gt;");
          }

          function normalizeTerminalValues(values = {}) {
            return {
              model: values.model || "",
              extension: values.extension || "",
              serial: values.serial || values.serial_number || "",
              mac: values.mac || "",
              ip: values.ip || "",
              ownership: values.ownership || "propio",
              dectBase: values.dectBase || values.dect_base || "",
            };
          }

          function addTerminalRow(rawValues = {}) {
            const values = normalizeTerminalValues(rawValues);
            const row = document.createElement("div");
            row.className = "terminal-row";
            const modelOptions = ['<option value="">Selecciona un modelo</option>']
              .concat(terminalModels.map(function (model) {
                return `<option value="${model}"${values.model === model ? " selected" : ""}>${model}</option>`;
              }))
              .join("");
            const dectBaseOptions = ['<option value="">—</option>']
              .concat(DECT_BASE_MODELS.map(function (baseModel) {
                return `<option value="${baseModel}"${values.dectBase === baseModel ? " selected" : ""}>${baseModel}</option>`;
              }))
              .join("");
            row.innerHTML = `
              <label class="row-field">
                <span class="field-mobile-label">Modelo</span>
                <select data-field="model" aria-label="Modelo de terminal">${modelOptions}</select>
              </label>
              <label class="row-field">
                <span class="field-mobile-label">Base DECT</span>
                <select data-field="dect-base" class="dect-base-field${values.dectBase || isDectHandset(values.model) ? "" : " is-hidden"}" aria-label="Base DECT">${dectBaseOptions}</select>
              </label>
              <label class="row-field">
                <span class="field-mobile-label">Extensión</span>
                <input data-field="extension" type="text" inputmode="numeric" placeholder="Extensión" value="${escapeAttribute(values.extension)}" aria-label="Extensión">
              </label>
              <label class="row-field">
                <span class="field-mobile-label">Serial</span>
                <input data-field="serial" type="text" placeholder="Serial number" value="${escapeAttribute(values.serial)}" aria-label="Serial number">
              </label>
              <label class="row-field">
                <span class="field-mobile-label">MAC</span>
                <input data-field="mac" type="text" placeholder="MAC" value="${escapeAttribute(values.mac)}" aria-label="MAC">
              </label>
              <label class="row-field">
                <span class="field-mobile-label">IP</span>
                <input data-field="ip" type="text" placeholder="IP" value="${escapeAttribute(values.ip)}" aria-label="IP">
              </label>
              <label class="row-field">
                <span class="field-mobile-label">Propiedad</span>
                <select data-field="ownership" aria-label="Propiedad">
                  <option value="propio"${values.ownership !== "ajeno" ? " selected" : ""}>Propio</option>
                  <option value="ajeno"${values.ownership === "ajeno" ? " selected" : ""}>Ajeno</option>
                </select>
              </label>
              <button type="button" class="remove-terminal" title="Eliminar terminal" aria-label="Eliminar terminal">×</button>`;
            row.querySelectorAll("input, select").forEach(function (field) {
              field.addEventListener("input", syncTerminalRows);
              field.addEventListener("change", syncTerminalRows);
            });
            row.querySelector('[data-field="model"]').addEventListener("change", function () {
              updateDectBaseField(row);
              syncTerminalRows();
            });
            if (values.dectBase) {
              row.querySelector('[data-field="dect-base"]').value = values.dectBase;
            }
            updateDectBaseField(row);
            row.querySelector(".remove-terminal").addEventListener("click", function () {
              row.remove();
              syncTerminalRows();
            });
            terminalRows.appendChild(row);
            syncTerminalRows();
          }

          function parseTerminalDetailLine(line) {
            const parts = line.split("|").map(function (part) { return part.trim(); });
            const hasModel = parts[0] && !/^\d+$/.test(parts[0]) && /[A-Za-z]/.test(parts[0]);
            if (hasModel) {
              if (parts.length >= 7) {
                return {
                  model: parts[0] || "",
                  extension: parts[1] || "",
                  serial: parts[2] || "",
                  mac: parts[3] || "",
                  ip: parts[4] || "",
                  ownership: (parts[5] || "propio").toLocaleLowerCase("es"),
                  dectBase: parts[6] || "",
                };
              }
              return {
                model: parts[0] || "",
                extension: parts[1] || "",
                serial: parts[2] || "",
                mac: parts[3] || "",
                ip: "",
                ownership: (parts[4] || "propio").toLocaleLowerCase("es"),
                dectBase: parts[5] || "",
              };
            }
            if (parts.length >= 6 && /^(propio|ajeno)$/i.test(parts[3] || "")) {
              return {
                extension: parts[0] || "",
                serial: parts[1] || "",
                mac: parts[2] || "",
                ip: "",
                ownership: (parts[3] || "propio").toLocaleLowerCase("es"),
                dectBase: parts[4] || "",
                model: parts[5] || "",
              };
            }
            return {
              extension: parts[0] || "",
              serial: parts[1] || "",
              mac: parts[2] || "",
              ip: parts[3] || "",
              ownership: (parts[4] || "propio").toLocaleLowerCase("es"),
              dectBase: parts[5] || "",
              model: parts[6] || "",
            };
          }

          function loadExistingTerminalRows() {
            const lines = terminalDetails.value.split(/\r?\n/).filter(function (line) {
              return line.trim();
            });
            if (!lines.length) {
              addTerminalRow();
              return;
            }
            lines.forEach(function (line) {
              addTerminalRow(parseTerminalDetailLine(line));
            });
            syncTerminalRows();
          }

          document.getElementById("add-terminal").addEventListener("click", function () {
            addTerminalRow();
            terminalRows.lastElementChild.querySelector('[data-field="model"]').focus();
          });
          document.querySelector(".creation-form").addEventListener("submit", syncTerminalRows);
          loadExistingTerminalRows();
          window.__drawioTerminals = {
            clear: function () {
              terminalRows.innerHTML = "";
              terminalDetails.value = "";
              terminalEquipmentText.value = "";
            },
            addRow: addTerminalRow,
            sync: syncTerminalRows,
          };

          window.__drawioConnectivity = {
            apply: function (data) {
              if (data.internet_tipo) {
                internetType.value = data.internet_tipo;
              }
              if (data.internet_proveedor) {
                internetProveedor.dataset.selected = data.internet_proveedor;
              }
              if (data.internet_velocidad) {
                internetVelocidad.dataset.selected = data.internet_velocidad;
              }
              updateInternetFields();
              if (data.internet_proveedor) {
                internetProveedor.value = data.internet_proveedor;
              }
              if (data.internet_velocidad) {
                internetVelocidad.value = data.internet_velocidad;
              }
              if (data.ont_modelo) {
                ontModel.value = data.ont_modelo;
              }
              if (data.router_modelo) {
                routerModel.value = data.router_modelo;
              }
              if (data.backup_modelo) {
                backupModel.value = data.backup_modelo;
              }
              const routerIpField = document.querySelector('input[name="router_ip"]');
              if (routerIpField && data.router_ip) {
                routerIpField.value = data.router_ip;
              }
              updateBackupSelector();
            },
          };

          const importButton = document.getElementById("import-work-order");
          const importStatus = document.getElementById("import-work-order-status");
          const importGlpiStatus = document.getElementById("import-glpi-status");
          const importWarnings = document.getElementById("import-work-order-warnings");
          const workOrderPaste = document.getElementById("work-order-paste");

          function csrfTokenValue() {
            const pageToken = document.getElementById("page-csrf-token");
            const formToken = document.querySelector('input[name="csrf_token"]');
            return (pageToken && pageToken.value) || (formToken && formToken.value) || "";
          }

          function renderImportWarnings(warnings) {
            if (!importWarnings) {
              return;
            }
            importWarnings.innerHTML = "";
            (warnings || []).forEach(function (warning) {
              const item = document.createElement("li");
              item.textContent = warning;
              importWarnings.appendChild(item);
            });
          }

          function renderGlpiSuggestions(suggestions) {
            const panel = document.getElementById("import-glpi-suggestions");
            if (!panel) {
              return;
            }
            panel.innerHTML = "";
            if (!suggestions || !suggestions.length) {
              panel.hidden = true;
              return;
            }
            panel.hidden = false;

            const title = document.createElement("p");
            title.className = "glpi-suggestions-title";
            title.textContent = "Opciones posibles en GLPI (elige una o selecciona manualmente abajo):";
            panel.appendChild(title);

            const list = document.createElement("div");
            list.className = "glpi-suggestions-list";
            suggestions.forEach(function (item) {
              const btn = document.createElement("button");
              btn.type = "button";
              btn.className = "glpi-suggestion-card";

              const heading = document.createElement("strong");
              heading.textContent = `${item.cliente} / ${item.sede}`;
              btn.appendChild(heading);

              const meta = document.createElement("span");
              meta.className = "glpi-suggestion-meta";
              const parts = [item.province];
              if (item.cif) parts.push(`CIF ${item.cif}`);
              if (item.reasons && item.reasons.length) parts.push(item.reasons.join(", "));
              meta.textContent = parts.join(" · ");
              btn.appendChild(meta);

              if (item.direccion) {
                const addr = document.createElement("span");
                addr.className = "glpi-suggestion-address";
                addr.textContent = item.direccion;
                btn.appendChild(addr);
              }

              btn.addEventListener("click", function () {
                window.__drawioApplyGlpiSuggestion(item);
              });
              list.appendChild(btn);
            });
            panel.appendChild(list);
          }

          window.__drawioApplyGlpiSuggestion = function (item) {
            if (!item || !item.glpi_entity_id) {
              return;
            }
            const ok = window.__drawioGlpiSelectByEntityId
              ? window.__drawioGlpiSelectByEntityId(item.glpi_entity_id)
              : false;
            const clienteField = document.getElementById("cliente");
            const cifField = document.getElementById("cif");
            const sedeField = document.getElementById("sede");
            const direccionField = document.getElementById("direccion");
            const entityField = document.getElementById("glpi-entity-id");
            if (item.cliente) clienteField.value = item.cliente;
            if (item.cif) cifField.value = item.cif;
            if (item.sede) sedeField.value = item.sede;
            if (item.direccion) direccionField.value = item.direccion;
            entityField.value = String(item.glpi_entity_id);
            if (importGlpiStatus) {
              importGlpiStatus.textContent = ok
                ? `GLPI seleccionado: ${item.cliente} / ${item.sede}`
                : `Datos aplicados: ${item.cliente} / ${item.sede}. Revisa la sede en el desplegable.`;
            }
            renderGlpiSuggestions([]);
            const source = document.getElementById("address-source");
            if (source) {
              source.textContent = "Dirección de la opción elegida. Puedes corregirla si ha cambiado.";
            }
          };

          function applyImportedForm(data) {
            const clienteField = document.getElementById("cliente");
            const cifField = document.getElementById("cif");
            const sedeField = document.getElementById("sede");
            const direccionField = document.getElementById("direccion");
            const entityField = document.getElementById("glpi-entity-id");

            if (data.cliente) clienteField.value = data.cliente;
            if (data.cif) cifField.value = data.cif;
            if (data.sede) sedeField.value = data.sede;
            if (data.direccion) direccionField.value = data.direccion;

            const confidence = data.glpi_confidence || (data.glpi_matched ? "high" : "none");
            let glpiMessage = data.glpi_message || "";

            if (confidence === "high" && data.glpi_entity_id) {
              entityField.value = String(data.glpi_entity_id);
              if (window.__drawioGlpiSelectByEntityId) {
                window.__drawioGlpiSelectByEntityId(data.glpi_entity_id);
              }
              if (data.cliente) clienteField.value = data.cliente;
              if (data.cif) cifField.value = data.cif;
              if (data.sede) sedeField.value = data.sede;
              if (data.direccion) direccionField.value = data.direccion;
              renderGlpiSuggestions([]);
            } else {
              entityField.value = "";
              renderGlpiSuggestions(data.glpi_suggestions || []);
              if (!glpiMessage && (data.glpi_suggestions || []).length) {
                glpiMessage = "Elige una opción similar o selecciona provincia, cliente y sede manualmente.";
              }
            }

            if (importGlpiStatus) {
              importGlpiStatus.textContent = glpiMessage;
              importGlpiStatus.classList.toggle("is-warn", confidence !== "high");
            }
            if (window.__drawioConnectivity) {
              window.__drawioConnectivity.apply(data);
            }
            if (window.__drawioDevices) {
              window.__drawioDevices.clear();
              (data.devices_json || []).forEach(function (device) {
                window.__drawioDevices.addRow(device);
              });
              window.__drawioDevices.sync();
            }
            if (window.__drawioTerminals) {
              window.__drawioTerminals.clear();
              const terminals = data.terminals || [];
              if (!terminals.length) {
                window.__drawioTerminals.addRow();
              } else {
                terminals.forEach(function (terminal) {
                  window.__drawioTerminals.addRow(terminal);
                });
              }
              window.__drawioTerminals.sync();
            }
          }

          if (importButton) {
            function resizePasteField() {
              if (!workOrderPaste) {
                return;
              }
              workOrderPaste.style.height = "auto";
              workOrderPaste.style.height = Math.min(workOrderPaste.scrollHeight, 120) + "px";
            }

            function buildImportPayload(text) {
              const trimmed = (text || "").trim();
              if (!trimmed) {
                return null;
              }
              if (trimmed.includes("\n") || trimmed.length > 160) {
                return { pasted_text: trimmed };
              }
              if (/^https?:\/\//i.test(trimmed)) {
                return { url: trimmed };
              }
              if (/^(?:OT)?0*\d{3,}$/i.test(trimmed)) {
                return { work_order_id: trimmed };
              }
              return { pasted_text: trimmed };
            }

            async function runImport() {
              const pastedText = (workOrderPaste && workOrderPaste.value || "").trim();
              const importPayload = buildImportPayload(pastedText);
              if (!importPayload) {
                importStatus.textContent = "Pega la OT, escribe el ID o un enlace.";
                if (workOrderPaste) {
                  workOrderPaste.focus();
                }
                return;
              }
              importButton.disabled = true;
              importStatus.textContent = "Rellenando...";
              if (importGlpiStatus) {
                importGlpiStatus.textContent = "";
              }
              renderImportWarnings([]);
              try {
                const csrfToken = csrfTokenValue();
                const response = await fetch(window.__DRAWIO_PAGE_CONFIG.importWorkOrderUrl, {
                  method: "POST",
                  credentials: "same-origin",
                  headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                  },
                  body: JSON.stringify(importPayload),
                });
                const body = await response.json();
                if (!response.ok) {
                  throw new Error(body.error || "No se ha podido rellenar el formulario.");
                }
                applyImportedForm(body);
                const label = body.work_order_id ? `OT ${body.work_order_id}` : "Oferta";
                importStatus.textContent = `${label} rellenada. Revisa el formulario de abajo.`;
                renderImportWarnings(body.warnings || []);
                const clienteField = document.getElementById("cliente");
                if (clienteField) {
                  clienteField.scrollIntoView({ behavior: "smooth", block: "center" });
                }
              } catch (error) {
                importStatus.textContent = error.message;
              } finally {
                importButton.disabled = false;
              }
            }

            importButton.addEventListener("click", runImport);

            if (workOrderPaste) {
              workOrderPaste.addEventListener("input", resizePasteField);
              workOrderPaste.addEventListener("paste", function () {
                window.setTimeout(resizePasteField, 0);
              });
              workOrderPaste.addEventListener("keydown", function (event) {
                if (event.ctrlKey && event.key === "Enter") {
                  event.preventDefault();
                  runImport();
                }
              });
            }
          }
})();
