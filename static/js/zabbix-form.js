(function () {
  const form = document.getElementById("zabbix-form");
  const provinceSelect = document.getElementById("zabbix-provincia");
  const groupStatus = document.getElementById("zabbix-group-status");
  const groupIdInput = document.getElementById("zabbix-groupid");
  const internetTipo = document.getElementById("zabbix-internet-tipo");
  const internetProveedor = document.getElementById("zabbix-internet-proveedor");
  const routerModelo = document.getElementById("zabbix-router-modelo");
  const backupModelo = document.getElementById("zabbix-backup-modelo");
  const providerWrap = document.getElementById("zabbix-provider-wrap");
  const backupWrap = document.getElementById("zabbix-backup-wrap");
  const backupIpWrap = document.getElementById("zabbix-backup-ip-wrap");
  const backupIpInput = document.getElementById("zabbix-backup-ip");
  const planPreview = document.getElementById("zabbix-plan-preview");
  const planSummary = document.getElementById("zabbix-plan-summary");
  const planHosts = document.getElementById("zabbix-plan-hosts");

  const groupLookupUrl = document.body.dataset.groupLookupUrl;
  const planLookupUrl = document.body.dataset.planLookupUrl;

  if (!form) {
    return;
  }

  let lookupTimer = null;
  let planTimer = null;

  function isChateau() {
    return (routerModelo && routerModelo.value || "").toUpperCase().includes("CHATEAU");
  }

  function isHap() {
    return (routerModelo && routerModelo.value || "").toLowerCase().includes("hap");
  }

  function isFibraBackup() {
    return (internetTipo && internetTipo.value || "").toUpperCase().includes("FIBRA + BACK UP");
  }

  function isSolo4g() {
    return (internetTipo && internetTipo.value || "").toUpperCase().includes("4G MONITORIZADO");
  }

  function updateFieldVisibility() {
    const fibra = isFibraBackup();
    const solo4g = isSolo4g();

    if (providerWrap) {
      providerWrap.hidden = solo4g;
      if (internetProveedor) {
        internetProveedor.required = !solo4g;
      }
    }

    if (backupWrap) {
      const showBackup = fibra && isHap();
      backupWrap.hidden = !showBackup;
      if (backupModelo) {
        backupModelo.required = showBackup;
      }
    }

    if (backupIpWrap && backupIpInput) {
      const showBackupIp = fibra && isHap() && backupModelo && backupModelo.value;
      backupIpWrap.hidden = !showBackupIp;
      backupIpInput.required = showBackupIp;
    }

    if (solo4g && routerModelo && !isChateau()) {
      routerModelo.value = "CHATEAU";
    }
  }

  function setGroupStatus(message, state) {
    if (!groupStatus) {
      return;
    }
    groupStatus.textContent = message;
    groupStatus.className = "zabbix-group-status";
    if (state) {
      groupStatus.classList.add("is-" + state);
    }
  }

  async function lookupGroup(province) {
    if (!groupLookupUrl || !provinceSelect) {
      return;
    }
    if (!province) {
      if (groupIdInput) {
        groupIdInput.value = "";
      }
      setGroupStatus("Selecciona una provincia para asignar el grupo en Zabbix.", "");
      return;
    }

    setGroupStatus("Buscando grupo en Zabbix...", "loading");
    try {
      const response = await fetch(
        groupLookupUrl + "?provincia=" + encodeURIComponent(province),
        { credentials: "same-origin" }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "No se pudo consultar el grupo.");
      }
      if (groupIdInput) {
        groupIdInput.value = payload.groupid || "";
      }
      setGroupStatus("Grupo: " + (payload.name || province), "ok");
    } catch (error) {
      if (groupIdInput) {
        groupIdInput.value = "";
      }
      setGroupStatus(error.message || "Provincia no encontrada en Zabbix.", "error");
    }
  }

  function buildPlanQuery() {
    const params = new URLSearchParams();
    [
      "cliente",
      "sede",
      "internet_tipo",
      "internet_proveedor",
      "router_modelo",
      "backup_modelo",
      "router_ip",
      "backup_ip",
    ].forEach(function (name) {
      const field = form.querySelector('[name="' + name + '"]');
      if (field && field.value) {
        params.set(name, field.value);
      }
    });
    return params.toString();
  }

  async function refreshPlan() {
    if (!planLookupUrl || !planPreview || !planSummary || !planHosts) {
      return;
    }

    const query = buildPlanQuery();
    if (!query.includes("internet_tipo=") || !query.includes("router_modelo=") || !query.includes("router_ip=")) {
      planPreview.hidden = true;
      return;
    }

    try {
      const response = await fetch(planLookupUrl + "?" + query, { credentials: "same-origin" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "No se pudo calcular el plan.");
      }
      planSummary.textContent = payload.summary || "";
      planHosts.innerHTML = "";
      (payload.hosts || []).forEach(function (host) {
        const item = document.createElement("li");
        item.textContent = host.name + " · " + host.ip + " · " + host.template_label;
        planHosts.appendChild(item);
      });
      planPreview.hidden = false;
    } catch (error) {
      planSummary.textContent = error.message || "";
      planHosts.innerHTML = "";
      planPreview.hidden = false;
    }
  }

  function schedulePlanRefresh() {
    clearTimeout(planTimer);
    planTimer = setTimeout(refreshPlan, 250);
  }

  function scheduleGroupLookup() {
    if (!provinceSelect) {
      return;
    }
    clearTimeout(lookupTimer);
    lookupTimer = setTimeout(function () {
      lookupGroup(provinceSelect.value.trim());
    }, 200);
  }

  if (provinceSelect) {
    provinceSelect.addEventListener("change", scheduleGroupLookup);
    if (provinceSelect.value.trim()) {
      lookupGroup(provinceSelect.value.trim());
    }
  }

  [
    internetTipo,
    internetProveedor,
    routerModelo,
    backupModelo,
    document.getElementById("zabbix-cliente"),
    document.getElementById("zabbix-sede"),
    document.getElementById("zabbix-router-ip"),
    backupIpInput,
  ].forEach(function (field) {
    if (!field) {
      return;
    }
    field.addEventListener("change", function () {
      updateFieldVisibility();
      schedulePlanRefresh();
    });
    field.addEventListener("input", schedulePlanRefresh);
  });

  updateFieldVisibility();
  schedulePlanRefresh();
})();
