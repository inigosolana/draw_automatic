(function () {
  var configElement = document.getElementById("drawio-page-config");
  window.__DRAWIO_PAGE_CONFIG = {};
  if (!configElement || !configElement.textContent) {
    return;
  }
  try {
    window.__DRAWIO_PAGE_CONFIG = JSON.parse(configElement.textContent);
  } catch (error) {
    console.warn("No se ha podido leer la configuracion de la pagina draw.io", error);
  }
})();
