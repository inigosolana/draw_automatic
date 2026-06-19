(function (global) {
  function createSearchSelect(element, onSelect) {
    if (!element) {
      return null;
    }

    var items = [];
    var selected = null;
    element.innerHTML =
      '<button type="button" class="search-select-trigger">' +
      "<span>" +
      element.dataset.placeholder +
      '</span><span class="search-select-arrow">▾</span></button>' +
      '<div class="search-select-menu">' +
      '<input type="search" class="search-select-filter" placeholder="Buscar...">' +
      '<div class="search-select-options"></div></div>';
    var trigger = element.querySelector(".search-select-trigger");
    var label = trigger.querySelector("span");
    var filter = element.querySelector(".search-select-filter");
    var options = element.querySelector(".search-select-options");

    function render(query) {
      var normalized = (query || "").toLocaleLowerCase("es");
      options.innerHTML = "";
      items
        .filter(function (item) {
          return item.nombre.toLocaleLowerCase("es").includes(normalized);
        })
        .forEach(function (item) {
          var button = document.createElement("button");
          button.type = "button";
          button.className = "search-select-option";
          button.textContent = item.nombre;
          button.addEventListener("click", function () {
            selected = item;
            label.textContent = item.nombre;
            element.classList.remove("open");
            filter.value = "";
            onSelect(item);
          });
          options.appendChild(button);
        });
      if (!options.children.length) {
        options.innerHTML = '<div class="search-select-empty">Sin resultados</div>';
      }
    }

    trigger.addEventListener("click", function () {
      if (element.classList.contains("disabled")) {
        return;
      }
      document.querySelectorAll(".search-select.open").forEach(function (other) {
        if (other !== element) {
          other.classList.remove("open");
        }
      });
      element.classList.toggle("open");
      if (element.classList.contains("open")) {
        render("");
        filter.focus();
      }
    });
    filter.addEventListener("input", function () {
      render(filter.value);
    });

    return {
      setItems: function (newItems, placeholder) {
        items = newItems;
        selected = null;
        label.textContent = placeholder;
        element.dataset.placeholder = placeholder;
        element.classList.toggle("disabled", !newItems.length);
        render("");
      },
    };
  }

  global.__drawioCreateSearchSelect = createSearchSelect;
})(window);
