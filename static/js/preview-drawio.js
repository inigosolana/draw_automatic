(function () {
  const configElement = document.getElementById("drawio-preview-config");
  const frame = document.getElementById("drawio-preview");
  if (!configElement || !frame) {
    return;
  }

  let config;
  try {
    config = JSON.parse(configElement.textContent);
  } catch (_error) {
    return;
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
    if (message.event === "init") {
      frame.contentWindow.postMessage(
        JSON.stringify({
          action: "load",
          xml: config.xml,
          autosave: 0,
        }),
        "*"
      );
    }
  });
})();
