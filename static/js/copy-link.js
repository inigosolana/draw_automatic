// Copiar al portapapeles cualquier botón/enlace con [data-copy-url].
// Autónomo y reutilizable en Mis diagramas, Consultar diagramas y admin.
(function () {
  "use strict";

  function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        if (ok) resolve();
        else reject(new Error("copy failed"));
      } catch (e) {
        reject(e);
      }
    });
  }

  function wire(btn) {
    if (!btn || btn.dataset.copyWired) return;
    btn.dataset.copyWired = "1";
    var original = btn.textContent;
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var url = btn.dataset.copyUrl;
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

  function wireAll(root) {
    var scope = root || document;
    Array.prototype.forEach.call(scope.querySelectorAll("[data-copy-url]"), wire);
  }

  // Expuesto por si otra parte inyecta botones dinámicamente.
  window.wireCopyLinks = wireAll;

  document.addEventListener("DOMContentLoaded", function () {
    wireAll(document);
  });
})();
