// Gestión de filas de terminales (telefonía). Autocontenido: solo expone
// window.__drawioTerminals (clear/addRow/sync) que usa la importación de OT.
(function () {
          const terminalRows = document.getElementById("terminal-rows");
          const terminalDetails = document.getElementById("terminal-details");
          const terminalEquipmentText = document.getElementById("terminal-equipment-text");
          if (!terminalRows || !terminalDetails || !terminalEquipmentText) {
            return;
          }
          const terminalModels = ["FANVIL V62", "FANVIL V64", "FANVIL X303G", "T-30", "T-31", "T-33", "T-43", "T-44", "T-73", "W71H", "W72H", "W53H", "W73H"];
          function brandOf(model) {
            const m = (model || "").toLowerCase();
            if (/fanvil/.test(m)) return { cls: "b-fanvil", txt: "F" };
            if (/yealink|sip-t|\bt-?3\d|\bt-?4\d|\bt-?7\d|^w\d/.test(m)) return { cls: "b-yealink", txt: "Y" };
            if (/grandstream|gwn|gxp|grp/.test(m)) return { cls: "b-grandstream", txt: "G" };
            if (/tp-?link|deco/.test(m)) return { cls: "b-tplink", txt: "TP" };
            if (/d-?link|dgs/.test(m)) return { cls: "b-dlink", txt: "DL" };
            if (/ruijie/.test(m)) return { cls: "b-ruijie", txt: "RJ" };
            if (/tenda/.test(m)) return { cls: "b-tenda", txt: "TD" };
            if (/mikrotik|microtik|hap|chateau/.test(m)) return { cls: "b-mikrotik", txt: "MT" };
            return null;
          }
          function setRowBrand(row) {
            const badge = row.querySelector("[data-brand]");
            if (!badge) return;
            const sel = row.querySelector('[data-field="model"]');
            const br = brandOf(sel ? sel.value : "");
            badge.className = "brand-badge " + (br ? br.cls : "b-empty");
            badge.textContent = br ? br.txt : "";
          }
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

          // Estado de switches publicado por device-picker. Preferimos el
          // objeto agrupado (__DRAWIO_SWITCHES); si no está, caemos al número
          // de compat (__DRAWIO_SWITCH_PORTS) tratándolo como 1 switch.
          function currentSwitchState() {
            const sw = window.__DRAWIO_SWITCHES;
            if (sw && typeof sw === "object") {
              const count = typeof sw.count === "number" ? sw.count : 0;
              return {
                count: count,
                telPorts: typeof sw.telPorts === "number" ? sw.telPorts : 0,
                datPorts: typeof sw.datPorts === "number" ? sw.datPorts : 0,
                telPiso: sw.telPiso || "",
                datPiso: sw.datPiso || "",
                routerPiso: sw.routerPiso || "",
              };
            }
            const ports = window.__DRAWIO_SWITCH_PORTS;
            if (typeof ports === "number" && ports > 0) {
              return { count: 1, telPorts: ports, datPorts: 0, telPiso: "", datPiso: "", routerPiso: "" };
            }
            return { count: 0, telPorts: 0, datPorts: 0, telPiso: "", datPiso: "", routerPiso: "" };
          }

          function pisoDePuerto(puerto, state) {
            const p = String(puerto || "").toUpperCase();
            if (p.indexOf("TEL-") === 0) return state.telPiso || "";
            if (p.indexOf("DAT-") === 0) return state.datPiso || "";
            if (/^ETH[345]$/.test(p)) return state.routerPiso || "";
            if (/^ETH\d+$/.test(p) && state.count === 1) return state.telPiso || "";
            return "";
          }

          function optionHtml(value, label, selectedValue) {
            return `<option value="${value}"${selectedValue === value ? " selected" : ""}>${label}</option>`;
          }

          // Mismo esquema que device-picker:
          //   0 switches → Auto + ETH3/4/5.
          //   1 switch   → Auto + ETH1..ETHn (sin prefijo).
          //   2+ switches → Auto + optgroups TEL-/DAT-.
          function puertoOptionsHtml(selectedValue) {
            const state = currentSwitchState();
            const options = ['<option value="">Auto</option>'];
            // Router principal (hAP) SIEMPRE disponible (ETH3/4/5).
            const routerPorts = ["ETH3", "ETH4", "ETH5"]
              .map(function (v) { return optionHtml(v, "Router · " + v, selectedValue); }).join("");
            options.push(`<optgroup label="Router principal (hAP)">${routerPorts}</optgroup>`);
            if (state.count >= 1) {
              const swLabel = state.count >= 2 ? "Switch 1" : "Switch";
              const tel = [];
              for (let i = 1; i <= state.telPorts; i += 1) {
                tel.push(optionHtml("TEL-ETH" + i, swLabel + " · ETH" + i, selectedValue));
              }
              const label = state.count >= 2 ? "Switch 1 · Telefonía" : "Switch";
              options.push(`<optgroup label="${label}">${tel.join("")}</optgroup>`);
            }
            if (state.count >= 2) {
              const dat = [];
              for (let i = 1; i <= state.datPorts; i += 1) {
                dat.push(optionHtml("DAT-ETH" + i, "Switch 2 · ETH" + i, selectedValue));
              }
              options.push(`<optgroup label="Switch 2 · Datos">${dat.join("")}</optgroup>`);
            }
            return options.join("");
          }

          // Re-genera las opciones de puerto de todas las filas de terminal,
          // preservando el valor elegido si sigue siendo válido (o Auto).
          function refreshPortOptions() {
            terminalRows.querySelectorAll(".terminal-row").forEach(function (row) {
              const puertoField = row.querySelector('[data-field="puerto"]');
              if (!puertoField) {
                return;
              }
              const previous = puertoField.value;
              puertoField.innerHTML = puertoOptionsHtml(previous);
              if (puertoField.value !== previous) {
                puertoField.value = "";
              }
            });
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
            const puertoField = row.querySelector('[data-field="puerto"]');
            if (puertoField) {
              // Inverso al de DECT: el puerto solo aplica a terminales VoIP (no DECT).
              puertoField.disabled = showDect;
              puertoField.classList.toggle("is-hidden", showDect);
              if (showDect) {
                puertoField.value = "";
              }
            }
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
              opts.push('<option value="' + i + '"' + (String(selected) === String(i) ? " selected" : "") + ">Piso " + i + "</option>");
            }
            return opts.join("");
          }

          function updateFloorVisibility() {
            const cb = document.getElementById("tiene-pisos");
            const tienePisos = cb ? cb.checked : false;
            const state = currentSwitchState();
            terminalRows.querySelectorAll(".terminal-row").forEach(function (row) {
              const floor = row.querySelector(".terminal-floor");
              if (!floor) return;
              const sel = floor.querySelector('[data-field="piso"]');
              if (tienePisos) {
                floor.style.display = "";
                if (sel) {
                  const prev = sel.value;
                  sel.innerHTML = floorOptionsHtml(prev);
                  if (sel.value !== prev) sel.value = "";
                  // Piso automático: el terminal hereda el piso del switch/router
                  // al que se conecta (según su puerto). Se muestra deshabilitado.
                  const pf = row.querySelector('[data-field="puerto"]');
                  const heredado = pisoDePuerto(pf ? pf.value : "", state);
                  if (heredado) {
                    sel.value = heredado;
                    sel.disabled = true;
                    sel.title = "Piso heredado del equipo al que se conecta";
                  } else {
                    sel.disabled = false;
                    sel.title = "";
                  }
                }
              } else {
                floor.style.display = "none";
                if (sel) { sel.value = ""; sel.disabled = false; }
              }
            });
          }

          document.addEventListener("drawio:pisos-changed", function () {
            updateFloorVisibility();
            syncTerminalRows();
          });

          function syncTerminalRows() {
            updateFloorVisibility();
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
              const puertoField = row.querySelector('[data-field="puerto"]');
              const puerto = puertoField ? puertoField.value.trim() : "";
              const pisoField = row.querySelector('[data-field="piso"]');
              const piso = pisoField ? pisoField.value.trim() : "";
              if (!model && !extension && !serial && !mac && !ip) return;
              // El puerto ETH (8º campo) solo se guarda para terminales VoIP (no DECT).
              const puertoDetail = !isDectHandset(model) ? puerto : "";
              // Piso (9º campo) para el contenedor de piso en el diagrama.
              detailLines.push([model, extension, serial, mac, ip, ownership, dectBase, puertoDetail, piso].join(" | "));
              if (model) {
                const extensionText = extension ? `, extension ${extension}` : "";
                const baseText = isDectHandset(model) && dectBase ? `, base ${dectBase}` : "";
                // El puerto ETH solo aplica a terminales VoIP (no DECT) y solo si se ha elegido.
                const puertoText = !isDectHandset(model) && puerto ? `, puerto ${puerto}` : "";
                equipmentLines.push(`1 ${model}${extensionText}${baseText}${puertoText} ${ownership}`);
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
              puerto: values.puerto || "",
              piso: values.piso || "",
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
            const puertoOptions = puertoOptionsHtml(values.puerto);
            row.innerHTML = `
              <label class="row-field">
                <span class="field-mobile-label">Modelo</span>
                <span class="model-with-brand"><span class="brand-badge b-empty" data-brand aria-hidden="true"></span><select data-field="model" aria-label="Modelo de terminal">${modelOptions}</select></span>
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
                <span class="field-mobile-label">Puerto</span>
                <select data-field="puerto" class="puerto-field${isDectHandset(values.model) ? " is-hidden" : ""}" aria-label="Puerto ETH">${puertoOptions}</select>
              </label>
              <label class="row-field">
                <span class="field-mobile-label">Propiedad</span>
                <select data-field="ownership" aria-label="Propiedad">
                  <option value="propio"${values.ownership !== "ajeno" ? " selected" : ""}>Propio</option>
                  <option value="ajeno"${values.ownership === "ajeno" ? " selected" : ""}>Ajeno</option>
                </select>
              </label>
              <button type="button" class="remove-terminal" title="Eliminar terminal" aria-label="Eliminar terminal">×</button>
              <label class="row-field terminal-floor" style="grid-column:1/-1;display:none"><span class="field-mobile-label">Piso</span><select data-field="piso" aria-label="Piso">${floorOptionsHtml(values.piso)}</select></label>`;
            row.querySelectorAll("input, select").forEach(function (field) {
              field.addEventListener("input", syncTerminalRows);
              field.addEventListener("change", syncTerminalRows);
            });
            row.querySelector('[data-field="model"]').addEventListener("change", function () {
              updateDectBaseField(row);
              setRowBrand(row);
              syncTerminalRows();
            });
            setRowBrand(row);
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
          // Coordinación con device-picker: al cambiar los puertos del switch,
          // re-genera las opciones de puerto de todas las filas de terminal.
          document.addEventListener("drawio:switch-ports-changed", refreshPortOptions);
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
})();
