// tablet.js - Interacciones mejoradas para interfaz táctil/tablet

// ── Modal de confirmación personalizado ───────────────────────────────────────

function showConfirm(message, onConfirm, onCancel) {
  var modal = document.getElementById("custom-confirm-modal");
  if (!modal) return onConfirm && onConfirm(); // fallback si el modal no existe
  document.getElementById("custom-confirm-msg").textContent = message;
  modal.style.display = "flex";
  modal.classList.add("confirm-visible");

  var okBtn = document.getElementById("custom-confirm-ok");
  var cancelBtn = document.getElementById("custom-confirm-cancel");

  // Clonar para limpiar listeners previos
  var newOk = okBtn.cloneNode(true);
  var newCancel = cancelBtn.cloneNode(true);
  okBtn.parentNode.replaceChild(newOk, okBtn);
  cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);

  var handler;

  function closeModal() {
    modal.classList.remove("confirm-visible");
    modal.removeEventListener("click", handler);
    setTimeout(function () {
      modal.style.display = "none";
    }, 200);
  }

  newOk.addEventListener("click", function () {
    closeModal();
    if (onConfirm) onConfirm();
  });
  newCancel.addEventListener("click", function () {
    closeModal();
    if (onCancel) onCancel();
  });
  // Cerrar al hacer clic en el fondo
  handler = function (e) {
    if (e.target === modal) {
      closeModal();
    }
  };
  modal.addEventListener("click", handler);
}

// Interceptar formularios con data-confirm automáticamente
document.addEventListener("DOMContentLoaded", function () {
  document.addEventListener(
    "submit",
    function (e) {
      var form = e.target;
      var msg = form.dataset.confirm;
      if (!msg) return;
      e.preventDefault();
      showConfirm(msg, function () {
        delete form.dataset.confirm;
        form.submit();
      });
    },
    true,
  );
});

// ── Preservar posición de scroll en páginas de administración ─────────────────

document.addEventListener("DOMContentLoaded", function () {
  var savedPath = sessionStorage.getItem("scrollPath");
  var savedPos = sessionStorage.getItem("scrollPos");
  if (savedPath && savedPath === window.location.pathname && savedPos) {
    window.requestAnimationFrame(function () {
      window.scrollTo(0, parseInt(savedPos, 10));
    });
    sessionStorage.removeItem("scrollPos");
    sessionStorage.removeItem("scrollPath");
  }
});

document.addEventListener("submit", function (e) {
  // Solo guardar scroll en páginas de administración
  if (
    window.location.pathname.indexOf("/admin") !== -1 ||
    window.location.pathname.indexOf("/inventory") !== -1
  ) {
    sessionStorage.setItem("scrollPos", String(window.scrollY));
    sessionStorage.setItem("scrollPath", window.location.pathname);
  }
});

// ── Utilidades globales ───────────────────────────────────────────────────────

/**
 * Muestra una notificación tipo toast que desaparece sola.
 * @param {string} mensaje
 * @param {'error'|'success'|'info'} tipo
 * @param {number} duracion  milisegundos
 */
function mostrarToast(mensaje, tipo, duracion) {
  tipo = tipo || "info";
  duracion = duracion || 3500;

  var contenedor = document.getElementById("toast-container");
  if (!contenedor) {
    contenedor = document.createElement("div");
    contenedor.id = "toast-container";
    document.body.appendChild(contenedor);
  }

  var toast = document.createElement("div");
  toast.className = "toast toast-" + tipo;
  toast.textContent = mensaje;
  contenedor.appendChild(toast);

  setTimeout(function () {
    toast.classList.add("saliendo");
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 280);
  }, duracion);
}

/**
 * Resalta una sección con borde rojo y muestra un toast de error.
 * @param {string} selector  Selector CSS del elemento a resaltar
 * @param {string} mensaje
 */
function mostrarErrorEnSeccion(selector, mensaje) {
  mostrarToast(mensaje, "error");

  var el = document.querySelector(selector);
  if (!el) return;

  var seccion = el.closest(".customization-step") || el;
  seccion.classList.add("seccion-error");
  seccion.scrollIntoView({ behavior: "smooth", block: "center" });

  setTimeout(function () {
    seccion.classList.remove("seccion-error");
  }, 2500);
}

// ── Inicialización ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", function () {
  setupCancelButton();
  setupFormValidation();
  setupButtonFeedback();
  setupCashPaymentCalculation();
  if (!window._cartQuantitySetup) setupCartQuantityControls();
  setupFlashAutoDismiss();
  setupFormLoadingState();
  ensureTextSelection();

  window.tabletJsLoaded = true;
});

// ── Flash: cerrar automáticamente ────────────────────────────────────────────

function setupFlashAutoDismiss() {
  var alerts = document.querySelectorAll(".alert");
  alerts.forEach(function (alerta) {
    var btn = document.createElement("button");
    btn.className = "alert-cerrar";
    btn.textContent = "×"; // ×
    btn.setAttribute("aria-label", "Cerrar");
    btn.addEventListener("click", function () {
      cerrarAlerta(alerta);
    });
    alerta.appendChild(btn);

    setTimeout(function () {
      cerrarAlerta(alerta);
    }, 4000);
  });
}

function cerrarAlerta(alerta) {
  if (alerta.classList.contains("desvaneciendose")) return;
  alerta.classList.add("desvaneciendose");
  setTimeout(function () {
    if (alerta.parentNode) alerta.parentNode.removeChild(alerta);
  }, 450);
}

// ── Estado de carga en formularios ───────────────────────────────────────────

function setupFormLoadingState() {
  var formularios = document.querySelectorAll(
    "#customizationForm, .manual-coupon-form",
  );
  formularios.forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (e.defaultPrevented) return;
      var btn = form.querySelector(
        'button[type="submit"], input[type="submit"]',
      );
      if (!btn) return;
      btn.classList.add("btn-cargando");
      btn.disabled = true;
    });
  });
}

// ── Selección de texto ────────────────────────────────────────────────────────

function ensureTextSelection() {
  var style = document.createElement("style");
  style.textContent =
    "* { user-select: auto !important; -webkit-user-select: auto !important; }" +
    "input, label, button { pointer-events: auto !important; }";
  document.head.appendChild(style);
}

// ── Botón cancelar ────────────────────────────────────────────────────────────

function setupCancelButton() {
  var btn = document.getElementById("cancel-btn");
  if (!btn) return;
  btn.addEventListener("click", function () {
    var url = this.getAttribute("data-url");
    window.location.href = url || "/";
  });
}

// ── Validación de formulario ──────────────────────────────────────────────────

function setupFormValidation() {
  var form = document.getElementById("customizationForm");
  if (!form) return;

  var esBola = !!document.querySelector('.option-card input[value="Fría"]');
  var esSushi = !!document.querySelector(".preparation-options");
  var esComplementos = !!document.querySelector('input[name="sauces"]');
  var esBebida = !!document.querySelector('input[name="beverage_type"]');

  form.addEventListener("submit", function (e) {
    // Estilo (Fría / Empanizada)
    if (esBola || esSushi) {
      if (!document.querySelector('input[name="style"]:checked')) {
        e.preventDefault();
        mostrarErrorEnSeccion(
          'input[name="style"]',
          esSushi
            ? "Por favor selecciona si deseas tu sushi Frío o Empanizado."
            : "Por favor selecciona si deseas tu bola de arroz Fría o Empanizada.",
        );
        return;
      }
    }

    // Salsa (bola o boneless)
    if (esBola || (!esSushi && !esComplementos && !esBebida)) {
      var sauceInputs = document.querySelectorAll('input[name="sauce"]');
      if (
        sauceInputs.length > 0 &&
        !document.querySelector('input[name="sauce"]:checked')
      ) {
        e.preventDefault();
        mostrarErrorEnSeccion(
          'input[name="sauce"]',
          "Por favor selecciona una salsa.",
        );
        return;
      }
    }

    // Sushi: preparado + ingredientes
    if (esSushi) {
      var prep = document.querySelector('input[name="prepared"]:checked');
      if (!prep) {
        e.preventDefault();
        mostrarErrorEnSeccion(
          'input[name="prepared"]',
          "Por favor selecciona una opción de preparado.",
        );
        return;
      }
      var sauceField = document.getElementById("sauce_field");
      if (sauceField) sauceField.value = prep.value;

      var nS = document.querySelectorAll(".ingredient-checkbox:checked").length;
      if (nS > 3) {
        e.preventDefault();
        mostrarErrorEnSeccion(
          ".ingredient-checkbox",
          "Solo puedes seleccionar hasta 3 ingredientes para el sushi.",
        );
        return;
      }
    }

    // Bola de arroz: límite ingredientes
    if (esBola) {
      var nB = document.querySelectorAll(".ingredient-checkbox:checked").length;
      if (nB > 6) {
        e.preventDefault();
        mostrarErrorEnSeccion(
          ".ingredient-checkbox",
          "Solo puedes seleccionar hasta 6 ingredientes.",
        );
        return;
      }
    }
  });
}

// ── Feedback táctil en botones ────────────────────────────────────────────────

function setupButtonFeedback() {
  document
    .querySelectorAll(
      ".action-button, .quantity-btn, .quick-amount-btn, .calc-btn",
    )
    .forEach(function (btn) {
      btn.addEventListener(
        "touchstart",
        function () {
          this.style.opacity = "0.8";
        },
        { passive: true },
      );
      btn.addEventListener(
        "touchend",
        function () {
          this.style.opacity = "1";
        },
        { passive: true },
      );
    });
}

// ── Cálculo de efectivo ───────────────────────────────────────────────────────

function setupCashPaymentCalculation() {
  var calcBtn = document.getElementById("calculate-change-btn");
  if (!calcBtn) return;

  calcBtn.addEventListener("click", calculateChange);

  document.querySelectorAll(".quick-amount-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var inp = document.getElementById("amount-given");
      if (inp) {
        inp.value = this.getAttribute("data-amount");
        calculateChange();
      }
    });
  });

  document
    .querySelectorAll(".calc-btn:not(.clear-btn)")
    .forEach(function (btn) {
      btn.addEventListener("click", function () {
        var inp = document.getElementById("amount-given");
        if (!inp) return;
        var val = this.getAttribute("data-value");
        var s =
          inp.selectionStart != null ? inp.selectionStart : inp.value.length;
        var en = inp.selectionEnd != null ? inp.selectionEnd : inp.value.length;
        inp.value = inp.value.substring(0, s) + val + inp.value.substring(en);
        inp.selectionStart = inp.selectionEnd = s + val.length;
      });
    });

  var clearBtn = document.querySelector(".clear-btn");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      var inp = document.getElementById("amount-given");
      var cambio = document.getElementById("change-due");
      var printBtn = document.getElementById("print-ticket");
      if (inp) {
        inp.value = "";
        inp.focus();
      }
      if (cambio) {
        cambio.textContent = "$0.00";
      }
      if (printBtn) printBtn.style.display = "none";
    });
  }

  var amtInp = document.getElementById("amount-given");
  if (amtInp) {
    amtInp.addEventListener("input", function () {
      var totalEl = document.getElementById("total-amount");
      if (!totalEl) return;
      var total = parseFloat(totalEl.textContent.replace("$", ""));
      var dado = parseFloat(this.value);
      var cambio = document.getElementById("change-due");
      var printBtn = document.getElementById("print-ticket");
      if (!isNaN(dado) && dado >= total) {
        calculateChange();
      } else {
        if (cambio) cambio.textContent = "$0.00";
        if (printBtn) printBtn.style.display = "none";
      }
    });
  }
}

function calculateChange() {
  var totalEl = document.getElementById("total-amount");
  var amtInp = document.getElementById("amount-given");
  var cambioEl = document.getElementById("change-due");
  var printBtn = document.getElementById("print-ticket");

  if (!totalEl || !amtInp || !cambioEl) return;

  var total = parseFloat(totalEl.textContent.replace("$", ""));
  var dado = parseFloat(amtInp.value);

  if (isNaN(dado)) {
    cambioEl.textContent = "$0.00";
    cambioEl.style.color = "#e74c3c";
    amtInp.style.borderColor = "#e74c3c";
    mostrarToast("Por favor ingresa un monto válido.", "error");
    return;
  }

  if (dado < total) {
    cambioEl.textContent = "$0.00";
    cambioEl.style.color = "#e74c3c";
    amtInp.style.borderColor = "#e74c3c";
    mostrarToast(
      "Monto insuficiente. Faltan $" + (total - dado).toFixed(2) + ".",
      "error",
    );
    return;
  }

  amtInp.style.borderColor = "";
  var cambio = Math.round((dado - total) * 100) / 100;
  cambioEl.textContent = "$" + cambio.toFixed(2);
  cambioEl.style.color = "#2b8a3e";

  if (printBtn) {
    printBtn.style.display = "block";
    var base = printBtn.getAttribute("href").split("?")[0];
    printBtn.setAttribute(
      "href",
      base + "?payment_method=cash&amount_paid=" + dado,
    );
  }

  if (navigator.vibrate) navigator.vibrate(50);
}

// ── Controles de cantidad en carrito ─────────────────────────────────────────

function setupCartQuantityControls() {
  var plusBtns = document.querySelectorAll(".quantity-btn.plus");
  var minusBtns = document.querySelectorAll(".quantity-btn.minus");
  if (plusBtns.length === 0 && minusBtns.length === 0) return;

  plusBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var idx = this.getAttribute("data-index");
      var inp = document.querySelector(
        '.quantity-input[data-index="' + idx + '"]',
      );
      if (!inp) return;
      var v = parseInt(inp.value);
      if (isNaN(v)) v = 1;
      inp.value = v + 1;
      updateQuantity(idx, inp.value);
    });
  });

  minusBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var idx = this.getAttribute("data-index");
      var inp = document.querySelector(
        '.quantity-input[data-index="' + idx + '"]',
      );
      if (!inp) return;
      var v = parseInt(inp.value);
      if (isNaN(v)) v = 1;
      if (v > 1) {
        inp.value = v - 1;
        updateQuantity(idx, inp.value);
      }
    });
  });

  document.querySelectorAll(".quantity-input").forEach(function (inp) {
    inp.addEventListener("change", function () {
      var idx = this.getAttribute("data-index");
      var v = parseInt(this.value);
      if (v < 1 || isNaN(v)) {
        v = 1;
        this.value = 1;
      }
      updateQuantity(idx, v);
    });
  });

  document.querySelectorAll(".item-action.delete").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      if (!confirm("¿Seguro que quieres eliminar este artículo?")) {
        e.preventDefault();
      }
    });
  });
}

function updateQuantity(index, quantity) {
  var csrf = document.querySelector('meta[name="csrf-token"]');
  fetch("/update_quantity/" + index + "/" + quantity, {
    method: "POST",
    headers: csrf ? { "X-CSRFToken": csrf.content } : {},
  })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (data) {
      if (data.success) {
        window.location.reload();
      } else {
        mostrarToast(
          data.error || "No se pudo actualizar la cantidad.",
          "error",
        );
      }
    })
    .catch(function () {
      mostrarToast(
        "No se pudo actualizar la cantidad. Intenta de nuevo.",
        "error",
      );
    });
}
