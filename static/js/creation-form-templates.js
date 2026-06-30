// Plantillas de conectividad (guardar/cargar/borrar) y sugerencias de valores
// frecuentes. Se comunica con el núcleo vía window.__drawioConnectivity.apply()
// y reacciona al evento "drawio:connectivity-applied" para fijar el baseline de
// aprendizaje y refrescar la pista de sugerencias.
(function () {
          const internetType = document.getElementById("internet-tipo");
          const internetVelocidad = document.getElementById("internet-velocidad");
          const internetProveedor = document.getElementById("internet-proveedor");
          const routerModel = document.getElementById("router-modelo");
          const ontModel = document.getElementById("ont-modelo");
          const backupModel = document.getElementById("backup-modelo");

          const baselineField = document.getElementById("autofill-baseline");
          const templatePicker = document.getElementById("template-picker");
          const templateSaveBtn = document.getElementById("template-save");
          const templateDeleteBtn = document.getElementById("template-delete");
          const templateStatus = document.getElementById("template-status");
          const suggestionsHint = document.getElementById("connectivity-suggestions");
          const pageConfig = window.__DRAWIO_PAGE_CONFIG || {};

          function csrfTokenValue() {
            const pageToken = document.getElementById("page-csrf-token");
            const formToken = document.querySelector('input[name="csrf_token"]');
            return (pageToken && pageToken.value) || (formToken && formToken.value) || "";
          }

          function currentConnectivity() {
            const routerIpField = document.querySelector('input[name="router_ip"]');
            return {
              internet_tipo: (internetType && internetType.value) || "",
              internet_velocidad: (internetVelocidad && internetVelocidad.value) || "",
              internet_proveedor: (internetProveedor && internetProveedor.value) || "",
              ont_modelo: (ontModel && ontModel.value) || "",
              router_modelo: (routerModel && routerModel.value) || "",
              backup_modelo: (backupModel && backupModel.value) || "",
              router_ip: (routerIpField && routerIpField.value) || "",
            };
          }

          // El baseline es lo que se autorrellenó (plantilla u OT). Si el técnico
          // cambia algo después, el servidor lo detecta como corrección y aprende.
          function setBaselineFromForm() {
            if (baselineField) {
              baselineField.value = JSON.stringify(currentConnectivity());
            }
          }

          function setTemplateStatus(message, isError) {
            if (!templateStatus) {
              return;
            }
            templateStatus.textContent = message || "";
            templateStatus.classList.toggle("is-error", Boolean(isError));
          }

          async function loadTemplateList() {
            if (!templatePicker || !pageConfig.templatesUrl) {
              return;
            }
            try {
              const response = await fetch(pageConfig.templatesUrl, {
                headers: { Accept: "application/json" },
              });
              const body = await response.json();
              const current = templatePicker.value;
              templatePicker.innerHTML =
                '<option value="">— Cargar una plantilla guardada —</option>';
              (body.templates || []).forEach(function (tpl) {
                const option = document.createElement("option");
                option.value = String(tpl.id);
                option.textContent = tpl.name;
                templatePicker.appendChild(option);
              });
              templatePicker.value = current;
              if (templateDeleteBtn) {
                templateDeleteBtn.hidden = !templatePicker.value;
              }
            } catch (error) {
              /* sin plantillas: no es crítico */
            }
          }

          if (templatePicker) {
            templatePicker.addEventListener("change", async function () {
              if (templateDeleteBtn) {
                templateDeleteBtn.hidden = !templatePicker.value;
              }
              if (!templatePicker.value || !pageConfig.templatesUrl) {
                return;
              }
              try {
                const response = await fetch(
                  pageConfig.templatesUrl + "/" + encodeURIComponent(templatePicker.value),
                  { headers: { Accept: "application/json" } }
                );
                const body = await response.json();
                if (body && body.payload && window.__drawioConnectivity) {
                  window.__drawioConnectivity.apply(body.payload);
                  setTemplateStatus("Plantilla «" + (body.name || "") + "» aplicada.", false);
                } else {
                  setTemplateStatus("No se pudo cargar la plantilla.", true);
                }
              } catch (error) {
                setTemplateStatus("No se pudo cargar la plantilla.", true);
              }
            });
          }

          if (templateSaveBtn) {
            templateSaveBtn.addEventListener("click", async function () {
              if (!pageConfig.templatesUrl) {
                return;
              }
              const name = (window.prompt("Nombre de la plantilla (ej. Fibra + Backup AIRE):") || "").trim();
              if (!name) {
                return;
              }
              const payload = Object.assign({ name: name }, currentConnectivity());
              try {
                const response = await fetch(pageConfig.templatesUrl, {
                  method: "POST",
                  headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfTokenValue(),
                  },
                  body: JSON.stringify(payload),
                });
                const body = await response.json();
                if (response.ok) {
                  setTemplateStatus("Plantilla «" + name + "» guardada.", false);
                  await loadTemplateList();
                } else {
                  setTemplateStatus(body.error || "No se pudo guardar la plantilla.", true);
                }
              } catch (error) {
                setTemplateStatus("No se pudo guardar la plantilla.", true);
              }
            });
          }

          if (templateDeleteBtn) {
            templateDeleteBtn.addEventListener("click", async function () {
              if (!templatePicker || !templatePicker.value || !pageConfig.templatesUrl) {
                return;
              }
              const label = templatePicker.options[templatePicker.selectedIndex].textContent;
              if (!window.confirm("¿Borrar la plantilla «" + label + "»?")) {
                return;
              }
              try {
                await fetch(
                  pageConfig.templatesUrl + "/" + encodeURIComponent(templatePicker.value),
                  { method: "DELETE", headers: { "X-CSRFToken": csrfTokenValue() } }
                );
                templatePicker.value = "";
                templateDeleteBtn.hidden = true;
                setTemplateStatus("Plantilla borrada.", false);
                await loadTemplateList();
              } catch (error) {
                setTemplateStatus("No se pudo borrar la plantilla.", true);
              }
            });
          }

          // Sugerencias: lo más usado con el proveedor/tipo elegido.
          const SUGGESTION_LABELS = {
            internet_velocidad: "velocidad",
            ont_modelo: "ONT",
            router_modelo: "router",
            backup_modelo: "backup",
          };
          let suggestionsTimer = null;
          async function refreshConnectivitySuggestions() {
            if (!suggestionsHint || !pageConfig.suggestionsUrl) {
              return;
            }
            const proveedor = (internetProveedor && internetProveedor.value) || "";
            const tipo = (internetType && internetType.value) || "";
            if (!proveedor && !tipo) {
              suggestionsHint.hidden = true;
              return;
            }
            try {
              const url =
                pageConfig.suggestionsUrl +
                "?proveedor=" +
                encodeURIComponent(proveedor) +
                "&tipo=" +
                encodeURIComponent(tipo);
              const response = await fetch(url, { headers: { Accept: "application/json" } });
              const body = await response.json();
              const suggestions = (body && body.suggestions) || {};
              const parts = [];
              Object.keys(SUGGESTION_LABELS).forEach(function (field) {
                const values = suggestions[field] || [];
                if (values.length) {
                  parts.push(SUGGESTION_LABELS[field] + ": " + values.slice(0, 3).join(" · "));
                }
              });
              if (parts.length) {
                suggestionsHint.textContent =
                  "💡 Lo más usado" +
                  (proveedor ? " con " + proveedor : "") +
                  " → " +
                  parts.join("  |  ");
                suggestionsHint.hidden = false;
              } else {
                suggestionsHint.hidden = true;
              }
            } catch (error) {
              suggestionsHint.hidden = true;
            }
          }
          function scheduleSuggestionsRefresh() {
            if (suggestionsTimer) {
              window.clearTimeout(suggestionsTimer);
            }
            suggestionsTimer = window.setTimeout(refreshConnectivitySuggestions, 200);
          }
          if (internetProveedor) {
            internetProveedor.addEventListener("change", scheduleSuggestionsRefresh);
          }
          if (internetType) {
            internetType.addEventListener("change", scheduleSuggestionsRefresh);
          }

          // Cuando el núcleo autorrellena la conectividad (plantilla u OT), fijamos
          // el baseline y refrescamos la pista.
          document.addEventListener("drawio:connectivity-applied", function () {
            setBaselineFromForm();
            refreshConnectivitySuggestions();
          });

          loadTemplateList();
          refreshConnectivitySuggestions();
})();
