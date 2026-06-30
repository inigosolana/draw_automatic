(function () {
  window.addEventListener("load", function () {
    const resultPanel = document.getElementById("generation-result");
    if (resultPanel) {
      resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    const button = document.getElementById("download-drawio");
    if (!button) {
      return;
    }

    const downloadUrl = button.dataset.downloadUrl;
    const filename = button.dataset.filename || "diagrama.drawio";
    const downloadMode = (resultPanel && resultPanel.dataset.downloadMode) || "fresh";

    async function triggerDownload() {
      const response = await fetch(downloadUrl, { credentials: "same-origin" });
      if (!response.ok) {
        throw new Error("No se ha podido preparar la descarga.");
      }
      const blob = await response.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(blobUrl);
    }

    button.addEventListener("click", function () {
      triggerDownload().catch(function () {
        window.open(downloadUrl, "_blank", "noopener");
      });
    });

    const confirmButton = document.getElementById("confirm-glpi");
    const confirmResult = document.getElementById("glpi-confirm-result");
    if (confirmButton) {
      const confirmOriginalHtml = confirmButton.innerHTML;

      async function doConfirm(allowDuplicate) {
        confirmButton.disabled = true;
        confirmButton.classList.add("is-busy");
        confirmButton.innerHTML = '<span class="btn-spinner" aria-hidden="true"></span> Publicando…';
        confirmResult.className = "helper-text confirm-status confirm-working";
        confirmResult.textContent = "Subiendo y asociando el diagrama a la sede…";
        try {
          const csrfToken = document.querySelector('input[name="csrf_token"]').value;
          const response = await fetch(confirmButton.dataset.confirmUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded",
              "X-CSRFToken": csrfToken,
            },
            body:
              "csrf_token=" +
              encodeURIComponent(csrfToken) +
              "&allow_duplicate=" +
              encodeURIComponent(allowDuplicate ? "1" : "0"),
          });
          const body = await response.text();
          if (!response.ok) {
            const err = new Error(body);
            err.status = response.status;
            throw err;
          }
          const result = JSON.parse(body);
          confirmResult.className = "helper-text confirm-status confirm-ok";
          confirmResult.innerHTML =
            '✓ Diagrama #' +
            result.id +
            ' publicado en GLPI. <a href="' +
            result.url +
            '" target="_blank" rel="noopener">Abrir en GLPI ↗</a>';
          confirmButton.remove();
        } catch (error) {
          confirmButton.disabled = false;
          confirmButton.classList.remove("is-busy");
          confirmButton.innerHTML = confirmOriginalHtml;
          if (error.status === 409 && !allowDuplicate) {
            // La sede ya tiene un diagrama: preguntar Sí/No y reintentar si procede.
            confirmResult.className = "helper-text confirm-status confirm-warn";
            confirmResult.textContent = error.message || "Esta sede ya tiene un diagrama.";
            const msg =
              (error.message || "Esta sede ya tiene un diagrama en GLPI.") +
              "\n\n¿Subir el diagrama igualmente?";
            if (window.confirm(msg)) {
              doConfirm(true);
            } else {
              confirmResult.textContent = "Subida cancelada. La sede ya tenía un diagrama.";
            }
            return;
          }
          confirmResult.className = "helper-text confirm-status confirm-bad";
          confirmResult.textContent =
            "No se ha podido publicar. " + (error.message || "Error desconocido.");
        }
      }

      confirmButton.addEventListener("click", function () {
        doConfirm(false);
      });
    }

    if (downloadMode === "fresh" || downloadMode === "saved") {
      triggerDownload().catch(function () {
        console.warn("La descarga automatica no se ha podido completar.");
      });
    }

    const resetButton = document.getElementById("reset-generation");
    if (resetButton) {
      resetButton.addEventListener("click", function () {
        if (window.__drawioResetForm) {
          window.__drawioResetForm({ reload: true });
          return;
        }
        const homeUrl =
          (window.__DRAWIO_PAGE_CONFIG && window.__DRAWIO_PAGE_CONFIG.homeUrl) || "/";
        window.location.assign(homeUrl);
      });
    }
  });
})();
