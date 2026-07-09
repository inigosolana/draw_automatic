(function () {
  window.addEventListener("load", function () {
    const resultPanel = document.getElementById("generation-result");
    if (resultPanel) {
      resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // --- Copiar al portapapeles el enlace del diagrama en GLPI ---
    function copyTextToClipboard(text) {
      if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
      }
      return new Promise(function (resolve, reject) {
        try {
          const ta = document.createElement("textarea");
          ta.value = text;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.focus();
          ta.select();
          const ok = document.execCommand("copy");
          document.body.removeChild(ta);
          if (ok) resolve();
          else reject(new Error("copy failed"));
        } catch (e) {
          reject(e);
        }
      });
    }

    function wireCopyButton(btn) {
      if (!btn || btn.dataset.copyWired) return;
      btn.dataset.copyWired = "1";
      const original = btn.textContent;
      btn.addEventListener("click", function () {
        const url = btn.dataset.copyUrl;
        if (!url) return;
        copyTextToClipboard(url)
          .then(function () {
            btn.textContent = "✓ ¡Enlace copiado!";
            btn.classList.add("is-copied");
            setTimeout(function () {
              btn.textContent = original;
              btn.classList.remove("is-copied");
            }, 1800);
          })
          .catch(function () {
            window.prompt("Copia el enlace del diagrama:", url);
          });
      });
    }

    Array.prototype.forEach.call(document.querySelectorAll("[data-copy-url]"), wireCopyButton);

    const button = document.getElementById("download-drawio");
    if (!button) {
      return;
    }

    const downloadUrl = button.dataset.downloadUrl;
    const filename = button.dataset.filename || "diagrama.drawio";
    const downloadMode = (resultPanel && resultPanel.dataset.downloadMode) || "fresh";

    let downloadInProgress = false;

    async function triggerDownload() {
      if (downloadInProgress) {
        return;
      }
      downloadInProgress = true;
      try {
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
      } finally {
        downloadInProgress = false;
      }
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
          const tokenEl = document.querySelector('input[name="csrf_token"]');
          if (!tokenEl) {
            confirmResult.className = "helper-text confirm-status confirm-error";
            confirmResult.textContent = "Falta el token CSRF, recarga la página";
            confirmButton.disabled = false;
            confirmButton.classList.remove("is-busy");
            confirmButton.innerHTML = confirmOriginalHtml;
            return;
          }
          const csrfToken = tokenEl.value;
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
          let result;
          try {
            result = JSON.parse(body);
          } catch (parseError) {
            // El servidor respondió OK pero con un cuerpo no-JSON (redirección,
            // proxy, respuesta vacía). El diagrama probablemente sí se publicó,
            // así que evitamos mostrar un error que induzca a reintentar/duplicar.
            confirmResult.className = "helper-text confirm-status confirm-ok";
            confirmResult.textContent =
              "Diagrama enviado a GLPI. Verifica en GLPI si aparece publicado.";
            confirmButton.remove();
            return;
          }
          confirmResult.className = "helper-text confirm-status confirm-ok";
          confirmResult.textContent = "✓ Diagrama #" + result.id + " publicado en GLPI.";
          // Inyectar botones prominentes en la fila de acciones (donde estaba el
          // botón de confirmar): abrir el diagrama en GLPI y copiar su enlace.
          const actions = document.querySelector(".generation-result-actions");
          if (actions && !document.getElementById("copy-glpi-link")) {
            const openLink = document.createElement("a");
            openLink.className = "button glpi";
            openLink.href = result.url;
            openLink.target = "_blank";
            openLink.rel = "noopener";
            openLink.textContent = "Abrir diagrama en GLPI";
            const copyBtn = document.createElement("button");
            copyBtn.type = "button";
            copyBtn.id = "copy-glpi-link";
            copyBtn.className = "button secondary";
            copyBtn.dataset.copyUrl = result.url;
            copyBtn.textContent = "Copiar enlace";
            actions.insertBefore(openLink, confirmButton);
            actions.insertBefore(copyBtn, confirmButton);
            wireCopyButton(copyBtn);
          }
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
