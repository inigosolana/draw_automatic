// Núcleo del formulario de creación: selectores de conectividad (tipo de
// internet, proveedor, velocidad/capacidad, router, ONT, backup) y el API global
// window.__drawioConnectivity (apply/reset) que usan plantillas y la importación
// de OT. Las otras piezas viven en creation-form-{terminals,templates,workorder}.js.
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
              if (ontModel.options[0]) ontModel.options[0].textContent = "No aplica con 4G monitorizado";
            } else {
              if (ontModel.options[0]) ontModel.options[0].textContent = "Selecciona una ONT";
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
              if (backupModel.options[0]) backupModel.options[0].textContent = "No aplica con 4G monitorizado";
              backupHelp.textContent = "Con 4G monitorizado el router debe ser CHATEAU. No hay ONT ni equipo de backup externo.";
              return;
            }

            const usesBackup = internetType.value === "FIBRA + BACK UP";
            const isChateau = routerModel.value === "CHATEAU";
            const canUseExternalBackup = usesBackup && !isChateau && isHapRouter(routerModel.value);

            if (isChateau) {
              backupModel.value = "";
              backupModel.disabled = true;
              if (backupModel.options[0]) backupModel.options[0].textContent = usesBackup
                ? "Integrado en CHATEAU"
                : "No necesario con CHATEAU";
              backupHelp.textContent = usesBackup
                ? "El backup 4G está integrado en el propio CHATEAU. No se añade ningún dispositivo externo."
                : "CHATEAU incluye conectividad móvil integrada; no necesita un equipo de backup independiente.";
              return;
            }

            backupModel.disabled = !canUseExternalBackup;
            if (backupModel.options[0]) backupModel.options[0].textContent = canUseExternalBackup
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
          document.querySelector(".creation-form").addEventListener("submit", function (event) {
            const btn = this.querySelector('button[type="submit"]');
            if (btn && btn.dataset.busy) {
              event.preventDefault();
              return;
            }
            if (internetType.value === "SOLO 4G MONITORIZADO") {
              routerModel.value = "CHATEAU";
              const capacity = providerCapacity(internetProveedor.value);
              if (capacity) {
                internetVelocidad.value = capacity;
              }
            }
            if (btn && !btn.dataset.busy) {
              btn.dataset.busy = "1";
              setTimeout(function () {
                btn.disabled = true;
                btn.classList.add("is-busy");
                btn.innerHTML = '<span class="btn-spinner" aria-hidden="true"></span> Generando diagrama…';
              }, 0);
            }
          });
          updateInternetFields();

          // API global usado por plantillas (creation-form-templates.js) y por la
          // importación de OT (creation-form-workorder.js).
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
              // MAC del backup 4G detectado en el ETH2 del router (para el dibujo).
              var backupMacField = document.getElementById("backup-mac");
              if (backupMacField) backupMacField.value = data.backup_mac || "";
              const routerIpField = document.querySelector('input[name="router_ip"]');
              if (routerIpField && data.router_ip) {
                routerIpField.value = data.router_ip;
              }
              updateBackupSelector();
              // Avisa a plantillas/aprendizaje de que se autorrellenó la conectividad.
              document.dispatchEvent(new CustomEvent("drawio:connectivity-applied"));
            },
            reset: function () {
              internetType.value = "";
              internetProveedor.dataset.selected = "";
              internetVelocidad.dataset.selected = "";
              updateInternetFields();
            },
          };
})();
