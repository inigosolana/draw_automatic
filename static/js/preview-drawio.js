(function () {
  function bootPreviewEditor() {
    const configElement = document.getElementById("drawio-preview-config");
    const frame = document.getElementById("drawio-preview");
    const statusBanner = document.getElementById("preview-status");
    const closeButton = document.getElementById("preview-close");
    if (!configElement || !frame) {
      return;
    }

    let config;
    try {
      config = JSON.parse(configElement.textContent);
    } catch (_error) {
      return;
    }

    const libraryUrl = config.libraryUrl || "";
    const libraryId = libraryUrl ? "U" + encodeURIComponent(libraryUrl) : "";
    let hasUnsavedChanges = false;
    let isSaving = false;
    let diagramXml = config.xml || "";
    let baselineXml = "";
    let diagramReady = false;

    function postToFrame(payload) {
      if (!frame.contentWindow) {
        return;
      }
      frame.contentWindow.postMessage(JSON.stringify(payload), "*");
    }

    function showStatus(message, type) {
      if (!statusBanner) {
        return;
      }
      statusBanner.hidden = false;
      statusBanner.textContent = message;
      statusBanner.className = "preview-status preview-status-" + (type || "info");
    }

    function configureLibrary() {
      const editorConfig = {
        defaultGridEnabled: false,
        defaultPageVisible: true,
        graph: {
          background: "#ffffff",
          gridColor: "#ffffff",
        },
      };
      if (libraryId) {
        showStatus(
          "Cargando biblioteca Ausarta. Puede tardar unos segundos por su tamaño.",
          "info"
        );
        editorConfig.defaultCustomLibraries = [libraryId];
        editorConfig.customLibraries = [libraryId];
        editorConfig.defaultLibraries = libraryId;
        editorConfig.appendCustomLibraries = true;
      }
      postToFrame({
        action: "configure",
        config: editorConfig,
      });
    }

    function fetchDiagramXml() {
      if (diagramXml) {
        return Promise.resolve(diagramXml);
      }
      if (!config.xmlUrl) {
        return Promise.reject(new Error("No hay XML disponible para cargar."));
      }
      return fetch(config.xmlUrl, { credentials: "same-origin" }).then(function (response) {
        if (!response.ok) {
          throw new Error("No se pudo cargar el diagrama.");
        }
        return response.text();
      });
    }

    function fitDiagramToView() {
      postToFrame({ action: "fit", border: 8, maxScale: 1.25 });
    }

    function markDiagramSaved(xml) {
      diagramXml = xml;
      baselineXml = xml;
      hasUnsavedChanges = false;
    }

    function noteDiagramChange(xml) {
      if (!baselineXml || !xml) {
        return;
      }
      if (xml !== baselineXml) {
        hasUnsavedChanges = true;
      }
    }

    function buildCloseUrl(savedChanges) {
      if (!config.closeUrl) {
        return null;
      }
      if (!savedChanges) {
        return config.closeUrl;
      }
      const separator = config.closeUrl.indexOf("?") >= 0 ? "&" : "?";
      return config.closeUrl + separator + "saved=1";
    }

    function loadDiagram() {
      if (diagramReady) {
        return;
      }
      fetchDiagramXml()
        .then(function (xml) {
          markDiagramSaved(xml);
          diagramReady = true;
          postToFrame({
            action: "load",
            xml: xml,
            autosave: 1,
            modified: false,
            fit: 1,
            maxFitScale: 1.25,
            border: 8,
            background: "#ffffff",
            exportProtocol: true,
          });
        })
        .catch(function (error) {
          showStatus(error.message || "No se pudo cargar el diagrama.", "error");
        });
    }

    function closePreview(savedChanges) {
      const target = buildCloseUrl(Boolean(savedChanges));
      if (target) {
        window.location.href = target;
        return;
      }
      if (window.history.length > 1) {
        window.history.back();
        return;
      }
      window.close();
    }

    function confirmDiscardChanges() {
      return window.confirm(
        "Has modificado el diagrama y no has pulsado Guardar.\n\n¿Salir sin guardar los cambios?"
      );
    }

    function requestClose() {
      if (hasUnsavedChanges && !confirmDiscardChanges()) {
        return;
      }
      closePreview(false);
    }

    function saveDiagram(xml, shouldExit) {
      if (!config.saveUrl) {
        showStatus("No hay destino de guardado configurado.", "error");
        return Promise.reject(new Error("missing save url"));
      }
      if (isSaving) {
        return Promise.resolve();
      }
      if (!xml) {
        return Promise.reject(new Error("No se recibio el XML del diagrama."));
      }
      if (baselineXml && xml === baselineXml) {
        showStatus("No hay cambios que guardar.", "info");
        if (shouldExit) {
          window.setTimeout(function () {
            closePreview(false);
          }, 250);
        }
        return Promise.resolve();
      }
      isSaving = true;
      showStatus("Guardando cambios...", "info");
      return fetch(config.saveUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": config.csrfToken || "",
        },
        body: JSON.stringify({ xml: xml }),
      })
        .then(function (response) {
          return response.json().then(function (payload) {
            if (!response.ok) {
              throw new Error(payload.error || "No se pudo guardar el diagrama.");
            }
            return payload;
          });
        })
        .then(function (payload) {
          markDiagramSaved(xml);
          const message =
            payload.message ||
            (payload.version_name
              ? "Diagrama guardado como " + payload.version_name + "."
              : "Diagrama guardado correctamente.");
          showStatus(message, "success");
          postToFrame({
            action: "status",
            message: message,
            modified: false,
          });
          if (shouldExit) {
            window.setTimeout(function () {
              closePreview(true);
            }, 350);
          }
        })
        .catch(function (error) {
          showStatus(error.message || "Error al guardar.", "error");
          postToFrame({
            action: "status",
            message: "Error al guardar",
            modified: true,
          });
          throw error;
        })
        .finally(function () {
          isSaving = false;
        });
    }

    window.addEventListener("message", function (event) {
      if (event.source !== frame.contentWindow) {
        return;
      }
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (_error) {
        return;
      }

      if (message.event === "configure") {
        configureLibrary();
        return;
      }

      if (message.event === "init") {
        loadDiagram();
        return;
      }

      if (message.event === "load") {
        hasUnsavedChanges = false;
        if (statusBanner && statusBanner.className.indexOf("preview-status-error") === -1) {
          statusBanner.hidden = true;
        }
        window.setTimeout(fitDiagramToView, 200);
        window.setTimeout(fitDiagramToView, 900);
        return;
      }

      if (message.event === "autosave") {
        noteDiagramChange(message.xml || "");
        return;
      }

      if (message.event === "save") {
        saveDiagram(message.xml || "", Boolean(message.exit));
        return;
      }

      if (message.event === "exit") {
        if (message.modified || hasUnsavedChanges) {
          if (!confirmDiscardChanges()) {
            return;
          }
        }
        closePreview(false);
      }
    });

    if (closeButton) {
      closeButton.addEventListener("click", requestClose);
    }

    window.addEventListener("beforeunload", function (event) {
      if (!hasUnsavedChanges) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    });

    if (config.embedUrl) {
      frame.src = config.embedUrl;
    }

    const editorShell = document.querySelector(".preview-editor-shell");
    if (editorShell && window.ResizeObserver) {
      const resizeObserver = new ResizeObserver(function () {
        if (diagramReady) {
          window.setTimeout(fitDiagramToView, 120);
        }
      });
      resizeObserver.observe(editorShell);
    }

    window.addEventListener("resize", function () {
      if (diagramReady) {
        fitDiagramToView();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootPreviewEditor);
  } else {
    bootPreviewEditor();
  }
})();
