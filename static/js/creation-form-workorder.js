// Importación de OT/oferta (pegar texto, ID o enlace), sugerencias de GLPI y
// reseteo del formulario. Se apoya en los API globales window.__drawioConnectivity
// (apply/reset), window.__drawioTerminals y window.__drawioDevices.
(function () {
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

          function renderExistingDiagrams(diagrams) {
            const panel = document.getElementById("import-existing-diagrams");
            if (!panel) {
              return;
            }
            panel.innerHTML = "";
            if (!diagrams || !diagrams.length) {
              panel.hidden = true;
              return;
            }
            panel.hidden = false;
            const title = document.createElement("p");
            title.className = "existing-diagrams-title";
            title.textContent =
              "⚠ Esta sede/cliente ya tiene " + diagrams.length +
              " diagrama(s) en GLPI. Puedes editar uno (añadir o quitar equipos) en vez de crear otro:";
            panel.appendChild(title);
            diagrams.forEach(function (d) {
              const row = document.createElement("div");
              row.className = "existing-diagram-row";
              const name = document.createElement("span");
              name.className = "existing-diagram-name";
              name.textContent = "#" + d.id + " " + (d.name || "");
              row.appendChild(name);
              if (d.preview_url) {
                const edit = document.createElement("a");
                edit.className = "button secondary quiet";
                edit.href = d.preview_url;
                edit.target = "_blank";
                edit.rel = "noopener";
                edit.textContent = "Editar aquí";
                row.appendChild(edit);
              }
              if (d.glpi_url) {
                const glpi = document.createElement("a");
                glpi.className = "button glpi quiet";
                glpi.href = d.glpi_url;
                glpi.target = "_blank";
                glpi.rel = "noopener";
                glpi.textContent = "Abrir en GLPI";
                row.appendChild(glpi);
              }
              panel.appendChild(row);
            });
          }

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
            renderExistingDiagrams(data.existing_diagrams || []);
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
            // Rellenar campos por JS no dispara "change"/"input", así que el
            // editor de cajas (que se reconstruye con esos eventos) no se
            // actualizaba tras importar una OT. Lo forzamos aquí.
            const creationForm = document.querySelector(".creation-form");
            if (creationForm) {
              creationForm.dispatchEvent(new Event("change", { bubbles: true }));
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
              renderExistingDiagrams([]);
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

          function resetCreationForm(options) {
            const settings = options || {};
            const homeUrl = (window.__DRAWIO_PAGE_CONFIG && window.__DRAWIO_PAGE_CONFIG.homeUrl) || "/";
            if (settings.reload || document.getElementById("generation-result")) {
              window.location.assign(homeUrl);
              return;
            }

            const form = document.querySelector(".creation-form");
            if (form) {
              form.reset();
            }

            const entityField = document.getElementById("glpi-entity-id");
            if (entityField) {
              entityField.value = "";
            }
            if (window.__drawioGlpiReset) {
              window.__drawioGlpiReset();
            }

            if (window.__drawioConnectivity) {
              window.__drawioConnectivity.reset();
            }

            const switchTelefonia = document.getElementById("switch-telefonia");
            if (switchTelefonia) {
              switchTelefonia.checked = true;
            }

            if (window.__drawioDevices) {
              window.__drawioDevices.clear();
              window.__drawioDevices.addRow({ category: "switch" });
              window.__drawioDevices.sync();
            }
            if (window.__drawioTerminals) {
              window.__drawioTerminals.clear();
              window.__drawioTerminals.addRow();
              window.__drawioTerminals.sync();
            }

            if (workOrderPaste) {
              workOrderPaste.value = "";
              workOrderPaste.style.height = "";
            }
            if (importStatus) {
              importStatus.textContent = "";
            }
            if (importGlpiStatus) {
              importGlpiStatus.textContent = "";
              importGlpiStatus.classList.remove("is-warn");
            }
            renderImportWarnings([]);
            renderGlpiSuggestions([]);
            renderExistingDiagrams([]);

            const clienteField = document.getElementById("cliente");
            if (clienteField) {
              clienteField.focus();
            }
          }

          window.__drawioResetForm = resetCreationForm;

          const resetFormButton = document.getElementById("reset-form");
          if (resetFormButton) {
            resetFormButton.addEventListener("click", function () {
              resetCreationForm();
            });
          }
})();
