/**
 * Banner Engine - Custom JavaScript
 *
 * Handles htmx event listeners, drag-and-drop file uploads,
 * preview zoom controls, toast notifications, and keyboard shortcuts.
 */

/* ==========================================================================
   CSRF Token Injection
   ========================================================================== */

/**
 * Automatically attach CSRF token to every htmx request.
 */
document.body.addEventListener("htmx:configRequest", function (event) {
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  if (csrfMeta) {
    event.detail.headers["X-CSRFToken"] = csrfMeta.getAttribute("content");
  }
});

/* ==========================================================================
   htmx Event Listeners
   ========================================================================== */

/**
 * initCanvasInteractions()
 * Single entry point that (re-)initialises every canvas module and syncs
 * lock state. Call this whenever the preview canvas DOM is replaced.
 */
function initCanvasInteractions() {
  CanvasDrag.init();
  CanvasTextEdit.init();
  CanvasSelect.init();
  applyLockStates();
  syncAllTextToAiTab();
}

/**
 * applyLockStates()
 * After a canvas re-render the fresh SVG groups lose their in-memory
 * data-locked attribute. Re-apply it from the AI-tab container state so
 * that CanvasTextEdit keeps honouring Rule B (locked → no inline edit).
 */
function applyLockStates() {
  var canvas = document.getElementById("preview-canvas");
  if (!canvas) return;
  var svg = canvas.querySelector("svg");
  if (!svg) return;
  document.querySelectorAll("[id^='ai-slot-container-']").forEach(function (container) {
    if (container.dataset.locked !== "true") return;
    var slotId = container.id.replace("ai-slot-container-", "");
    var group = svg.querySelector('g[data-slot-id="' + slotId + '"]');
    if (group) group.dataset.locked = "true";
  });
}

/* ==========================================================================
   Cross-tab lock state helpers (manual slot-edit tab ↔ AI tab ↔ canvas)
   ========================================================================== */

/**
 * setManualTabLocked(slotId, displayText)
 * Hides the slot's editors in the スロット編集 tab and shows a read-only
 * locked block with the generated text.
 */
function setManualTabLocked(slotId, displayText) {
  var lockedDiv  = document.getElementById("manual-slot-locked-"   + slotId);
  var lockedText = document.getElementById("manual-slot-locked-text-" + slotId);
  var editorsDiv = document.getElementById("manual-slot-editors-"  + slotId);
  if (lockedText) lockedText.textContent = displayText;
  if (lockedDiv)  lockedDiv.classList.remove("hidden");
  if (editorsDiv) editorsDiv.classList.add("hidden");
}

/**
 * resetManualTabToEdit(slotId)
 * Restores the slot's editors in the スロット編集 tab (inverse of setManualTabLocked).
 */
function resetManualTabToEdit(slotId) {
  var lockedDiv  = document.getElementById("manual-slot-locked-"  + slotId);
  var editorsDiv = document.getElementById("manual-slot-editors-" + slotId);
  if (lockedDiv)  lockedDiv.classList.add("hidden");
  if (editorsDiv) editorsDiv.classList.remove("hidden");
}

/**
 * unlockSlot(slotId)
 * Master unlock — called by the スロット編集 tab's "Edit" button.
 * Resets both sidebar tabs and removes the canvas data-locked flag.
 * Delegates to resetSlotToPromptMode (defined in editor.html) when available,
 * which in turn calls resetManualTabToEdit — so no double-call needed here.
 */
function unlockSlot(slotId) {
  if (typeof resetSlotToPromptMode === "function") {
    resetSlotToPromptMode(slotId); // handles AI tab + manual tab + SVG group
  } else {
    resetManualTabToEdit(slotId);
  }
}

/**
 * After every htmx swap, re-initialize dynamic components inside the
 * swapped fragment (e.g. char counters, drag-drop zones).
 */
document.body.addEventListener("htmx:afterSwap", function (event) {
  var target = event.detail.target;

  // Re-bind character counters inside the swapped region
  initCharCounters(target);

  // Re-bind drag-drop zones inside the swapped region
  initDragDropZones(target);

  // Re-attach canvas listeners and sync text when the preview is swapped
  if (
    target &&
    (target.id === "preview-canvas" || target.querySelector("#preview-canvas"))
  ) {
    setTimeout(initCanvasInteractions, 50);
  }

  // Apply fade-in animation to new content
  if (target && !target.classList.contains("no-fade")) {
    target.classList.add("fade-in");
    target.addEventListener(
      "animationend",
      function () {
        target.classList.remove("fade-in");
      },
      { once: true }
    );
  }
});

/**
 * htmx:load fires on each element inserted by htmx (belt-and-suspenders for
 * outerHTML swaps that target #preview-canvas via standard hx-swap).
 */
document.body.addEventListener("htmx:load", function (event) {
  var elt = event.detail.elt;
  if (!elt) return;
  if (
    elt.id === "preview-canvas" ||
    (elt.querySelector && elt.querySelector("#preview-canvas"))
  ) {
    setTimeout(initCanvasInteractions, 50);
  }
});

/**
 * Show a global loading indicator before any htmx request.
 */
document.body.addEventListener("htmx:beforeRequest", function () {
  var indicator = document.getElementById("global-loading-indicator");
  if (indicator) {
    indicator.style.display = "flex";
  }
});

/**
 * Hide the global loading indicator after every htmx request completes.
 */
document.body.addEventListener("htmx:afterRequest", function (event) {
  var indicator = document.getElementById("global-loading-indicator");
  if (indicator) {
    indicator.style.display = "none";
  }

  // Surface server-side toast triggers via HX-Trigger header
  if (event.detail.successful === false) {
    BannerToast.show(
      "error",
      "Request failed. Please try again.",
      "Error"
    );
  }
});

/**
 * Handle htmx response errors (network failures, 500s, etc.)
 */
document.body.addEventListener("htmx:responseError", function (event) {
  var status = event.detail.xhr ? event.detail.xhr.status : 0;
  var message;

  if (status === 422) {
    message = "Validation error. Please check your input.";
  } else if (status === 413) {
    message = "File too large. Maximum size is 10 MB.";
  } else if (status >= 500) {
    message = "Server error. Please try again later.";
  } else if (status === 0) {
    message = "Network error. Please check your connection.";
  } else {
    message = "An unexpected error occurred (HTTP " + status + ").";
  }

  BannerToast.show("error", message, "Error");
});

/**
 * Listen for custom toast events sent via HX-Trigger response header.
 *   e.g.  HX-Trigger: {"showToast": {"level": "success", "message": "Saved!"}}
 */
document.body.addEventListener("showToast", function (event) {
  var d = event.detail || {};
  BannerToast.show(d.level || "info", d.message || "", d.title || "");
});

/* ==========================================================================
   Character Counter Helper
   ========================================================================== */

function initCharCounters(root) {
  root = root || document;
  var fields = root.querySelectorAll("[data-max-chars]");

  fields.forEach(function (field) {
    var max = parseInt(field.getAttribute("data-max-chars"), 10);
    var counterId = field.getAttribute("data-counter-id");
    if (!counterId) return;

    function update() {
      var counter = document.getElementById(counterId);
      if (!counter) return;
      var len = field.value.length;
      counter.textContent = len + " / " + max;
      if (len > max) {
        counter.classList.add("over-limit");
      } else {
        counter.classList.remove("over-limit");
      }
    }

    field.addEventListener("input", update);
    update(); // initialize
  });
}

/* ==========================================================================
   File Drag-and-Drop Handler
   ========================================================================== */

function initDragDropZones(root) {
  root = root || document;
  var zones = root.querySelectorAll(".drag-drop-zone");

  zones.forEach(function (zone) {
    // Prevent re-initialization
    if (zone.dataset.initialized === "true") return;
    zone.dataset.initialized = "true";

    var fileInput = zone.querySelector('input[type="file"]');
    var uploadUrl = zone.getAttribute("data-upload-url") || "/api/assets/upload";
    var slotId = zone.getAttribute("data-slot-id") || "";

    // Drag enter / leave visual feedback
    zone.addEventListener("dragenter", function (e) {
      e.preventDefault();
      zone.classList.add("drag-over");
    });

    zone.addEventListener("dragover", function (e) {
      e.preventDefault();
      zone.classList.add("drag-over");
    });

    zone.addEventListener("dragleave", function (e) {
      e.preventDefault();
      // Only remove class if we leave the zone entirely
      if (!zone.contains(e.relatedTarget)) {
        zone.classList.remove("drag-over");
      }
    });

    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      zone.classList.remove("drag-over");

      var files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFileUpload(zone, files[0], uploadUrl, slotId);
      }
    });

    // Manual file selection via hidden input
    if (fileInput) {
      fileInput.addEventListener("change", function () {
        if (fileInput.files.length > 0) {
          handleFileUpload(zone, fileInput.files[0], uploadUrl, slotId);
        }
      });
    }
  });
}

/**
 * Upload a single file to the server with progress feedback.
 *
 * @param {HTMLElement} zone - The drag-drop-zone element.
 * @param {File} file - The File object to upload.
 * @param {string} url - The upload endpoint.
 * @param {string} slotId - The associated slot id.
 */
function handleFileUpload(zone, file, url, slotId) {
  // Client-side validation
  var maxSize = 10 * 1024 * 1024; // 10 MB
  var allowedTypes = ["image/jpeg", "image/png", "image/webp"];

  if (!allowedTypes.includes(file.type)) {
    BannerToast.show(
      "error",
      "Unsupported file type. Use JPEG, PNG, or WebP.",
      "Upload Error"
    );
    return;
  }

  if (file.size > maxSize) {
    BannerToast.show(
      "error",
      "File exceeds the 10 MB size limit.",
      "Upload Error"
    );
    return;
  }

  // Show preview immediately
  var reader = new FileReader();
  reader.onload = function (e) {
    var existing = zone.querySelector(".file-preview");
    if (existing) existing.remove();
    var img = document.createElement("img");
    img.className = "file-preview";
    img.src = e.target.result;
    zone.appendChild(img);
    zone.classList.add("has-file");
  };
  reader.readAsDataURL(file);

  // Upload via XMLHttpRequest for progress tracking
  var formData = new FormData();
  formData.append("file", file);
  if (slotId) formData.append("slot_id", slotId);

  var xhr = new XMLHttpRequest();
  xhr.open("POST", url, true);

  // Attach CSRF token
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  if (csrfMeta) {
    xhr.setRequestHeader("X-CSRFToken", csrfMeta.getAttribute("content"));
  }

  // Progress bar inside zone
  var progressWrap = zone.querySelector(".upload-progress");
  if (!progressWrap) {
    progressWrap = document.createElement("div");
    progressWrap.className = "upload-progress";
    progressWrap.innerHTML =
      '<div class="progress-bar"><div class="progress-bar-fill" style="width: 0%"></div></div>';
    zone.appendChild(progressWrap);
  }
  var fill = progressWrap.querySelector(".progress-bar-fill");

  xhr.upload.addEventListener("progress", function (e) {
    if (e.lengthComputable) {
      var pct = Math.round((e.loaded / e.total) * 100);
      fill.style.width = pct + "%";
    }
  });

  xhr.addEventListener("load", function () {
    if (xhr.status >= 200 && xhr.status < 300) {
      BannerToast.show("success", "Image uploaded successfully.", "Upload");
      fill.style.width = "100%";
      // Trigger htmx to refresh preview after upload
      htmx.trigger(document.body, "imageUploaded", {
        slotId: slotId,
        response: xhr.responseText,
      });
    } else {
      BannerToast.show("error", "Upload failed (HTTP " + xhr.status + ").", "Upload Error");
    }
    // Clean up progress bar after a short delay
    setTimeout(function () {
      if (progressWrap.parentNode) {
        progressWrap.remove();
      }
    }, 1500);
  });

  xhr.addEventListener("error", function () {
    BannerToast.show("error", "Network error during upload.", "Upload Error");
    if (progressWrap.parentNode) progressWrap.remove();
  });

  xhr.send(formData);
}

/* ==========================================================================
   Preview Zoom Controls
   ========================================================================== */

var BannerZoom = (function () {
  var ZOOM_STEPS = [25, 50, 75, 100, 150, 200, 300, 400];
  var currentZoom = 100;

  function getCanvas() {
    return document.querySelector(".preview-canvas .canvas-inner");
  }

  function getLevelDisplay() {
    return document.querySelector(".preview-canvas .zoom-level");
  }

  function applyZoom() {
    var canvas = getCanvas();
    if (!canvas) return;
    canvas.style.transform = "scale(" + currentZoom / 100 + ")";
    canvas.style.transformOrigin = "center center";

    var display = getLevelDisplay();
    if (display) {
      display.textContent = currentZoom + "%";
    }
  }

  function zoomIn() {
    for (var i = 0; i < ZOOM_STEPS.length; i++) {
      if (ZOOM_STEPS[i] > currentZoom) {
        currentZoom = ZOOM_STEPS[i];
        applyZoom();
        return;
      }
    }
  }

  function zoomOut() {
    for (var i = ZOOM_STEPS.length - 1; i >= 0; i--) {
      if (ZOOM_STEPS[i] < currentZoom) {
        currentZoom = ZOOM_STEPS[i];
        applyZoom();
        return;
      }
    }
  }

  function zoomReset() {
    currentZoom = 100;
    applyZoom();
  }

  function zoomFit() {
    var container = document.querySelector(".preview-canvas");
    var inner = getCanvas();
    if (!container || !inner) return;

    // Temporarily reset to measure natural size
    inner.style.transform = "scale(1)";
    var cw = container.clientWidth - 32;
    var ch = container.clientHeight - 32;
    var iw = inner.scrollWidth;
    var ih = inner.scrollHeight;
    if (iw === 0 || ih === 0) return;

    var ratio = Math.min(cw / iw, ch / ih, 1);
    currentZoom = Math.round(ratio * 100);
    applyZoom();
  }

  function getZoom() {
    return currentZoom;
  }

  return {
    zoomIn: zoomIn,
    zoomOut: zoomOut,
    zoomReset: zoomReset,
    zoomFit: zoomFit,
    getZoom: getZoom,
  };
})();

/* ==========================================================================
   Toast Notification System
   ========================================================================== */

var BannerToast = (function () {
  var TOAST_DURATION = 5000;
  var container = null;

  function ensureContainer() {
    if (!container || !document.body.contains(container)) {
      container = document.createElement("div");
      container.className = "toast-container";
      container.setAttribute("aria-live", "polite");
      container.setAttribute("aria-atomic", "false");
      document.body.appendChild(container);
    }
    return container;
  }

  /**
   * Show a toast notification.
   *
   * @param {"success"|"error"|"warning"|"info"} level
   * @param {string} message
   * @param {string} [title]
   * @param {number} [duration]  Auto-dismiss in ms. Pass 0 to keep persistent.
   */
  function show(level, message, title, duration) {
    var c = ensureContainer();
    duration = duration !== undefined ? duration : TOAST_DURATION;

    var iconMap = {
      success: "&#10003;",
      error: "&#10007;",
      warning: "&#9888;",
      info: "&#8505;",
    };

    var toast = document.createElement("div");
    toast.className = "toast toast-" + level;
    toast.setAttribute("role", "status");
    toast.innerHTML =
      '<span class="toast-icon">' +
      (iconMap[level] || iconMap.info) +
      "</span>" +
      '<div class="toast-body">' +
      (title ? '<div class="toast-title">' + escapeHtml(title) + "</div>" : "") +
      '<div class="toast-message">' +
      escapeHtml(message) +
      "</div>" +
      "</div>" +
      '<button class="toast-close" aria-label="Close">&times;</button>';

    // Close button handler
    toast.querySelector(".toast-close").addEventListener("click", function () {
      dismiss(toast);
    });

    c.appendChild(toast);

    // Auto-dismiss
    if (duration > 0) {
      setTimeout(function () {
        dismiss(toast);
      }, duration);
    }

    return toast;
  }

  function dismiss(toast) {
    if (!toast || toast.classList.contains("toast-exiting")) return;
    toast.classList.add("toast-exiting");
    toast.addEventListener(
      "animationend",
      function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      },
      { once: true }
    );
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  return { show: show, dismiss: dismiss };
})();

/* ==========================================================================
   Keyboard Shortcuts
   ========================================================================== */

document.addEventListener("keydown", function (event) {
  var isInput =
    event.target.tagName === "INPUT" ||
    event.target.tagName === "TEXTAREA" ||
    event.target.isContentEditable;

  // Ctrl+Z / Cmd+Z  - Undo placeholder
  if ((event.ctrlKey || event.metaKey) && event.key === "z" && !event.shiftKey) {
    if (!isInput) {
      event.preventDefault();
      // TODO: Implement full undo stack.
      BannerToast.show("info", "Undo is not yet implemented.", "Undo");
    }
  }

  // Ctrl+Shift+Z / Cmd+Shift+Z  - Redo placeholder
  if ((event.ctrlKey || event.metaKey) && event.key === "z" && event.shiftKey) {
    if (!isInput) {
      event.preventDefault();
      BannerToast.show("info", "Redo is not yet implemented.", "Redo");
    }
  }

  // Escape - close open panels
  if (event.key === "Escape") {
    var leftPanel = document.querySelector(".editor-left-panel.open");
    if (leftPanel) leftPanel.classList.remove("open");

    var rightSidebar = document.querySelector(".editor-right-sidebar.open");
    if (rightSidebar) rightSidebar.classList.remove("open");
  }

  // +/- for zoom when not in an input
  if (!isInput) {
    if (event.key === "+" || event.key === "=") {
      BannerZoom.zoomIn();
    } else if (event.key === "-") {
      BannerZoom.zoomOut();
    } else if (event.key === "0" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      BannerZoom.zoomReset();
    }
  }
});

/* ==========================================================================
   Canvas Drag-and-Drop
   ========================================================================== */

/**
 * CanvasDrag — enables direct drag-and-drop repositioning of slots on the
 * SVG preview canvas.
 *
 * Each slot <g> element is tagged by the server with:
 *   class="draggable-slot"  data-slot-id  data-x  data-y  data-w  data-h
 *
 * On mouseup the new percentage position is PATCHed to
 * /api/slots/{patternId}/{slotId}/position and the canvas is refreshed.
 */
var CanvasDrag = (function () {
  var _state = null;

  /** Attach drag listeners to all .draggable-slot groups in #preview-canvas. */
  function init() {
    var canvas = document.getElementById("preview-canvas");
    if (!canvas) return;

    var svg = canvas.querySelector("svg");
    if (!svg) return;

    var patternId = canvas.getAttribute("data-pattern-id");
    if (!patternId) return;

    svg.querySelectorAll("g.draggable-slot").forEach(function (group) {
      // Avoid double-binding across re-renders
      if (group.dataset.dragInit === "1") return;
      group.dataset.dragInit = "1";
      group.style.cursor = "move";

      group.addEventListener("mousedown", function (e) {
        // Ignore right-clicks and already-in-progress drags
        if (e.button !== 0 || _state) return;
        e.preventDefault();
        e.stopPropagation();
        // Dismiss any open text-edit overlay before starting a drag
        if (typeof CanvasTextEdit !== "undefined") CanvasTextEdit.dismiss();

        var svgRect = svg.getBoundingClientRect();
        _state = {
          group: group,
          svg: svg,
          svgRect: svgRect,
          patternId: patternId,
          slotId: group.getAttribute("data-slot-id"),
          startClientX: e.clientX,
          startClientY: e.clientY,
          originXPct: parseFloat(group.getAttribute("data-x") || "0"),
          originYPct: parseFloat(group.getAttribute("data-y") || "0"),
          moved: false,
        };

        document.addEventListener("mousemove", _onMove);
        document.addEventListener("mouseup", _onUp);
      });
    });
  }

  function _onMove(e) {
    if (!_state) return;

    var dx = e.clientX - _state.startClientX;
    var dy = e.clientY - _state.startClientY;

    if (!_state.moved && (Math.abs(dx) > 3 || Math.abs(dy) > 3)) {
      _state.moved = true;
    }
    if (!_state.moved) return;

    // Convert screen delta → SVG coordinate delta
    var viewBox = _state.svg.viewBox.baseVal;
    var svgDx = (dx / _state.svgRect.width) * viewBox.width;
    var svgDy = (dy / _state.svgRect.height) * viewBox.height;

    _state.group.setAttribute("transform", "translate(" + svgDx + "," + svgDy + ")");
  }

  function _onUp(e) {
    document.removeEventListener("mousemove", _onMove);
    document.removeEventListener("mouseup", _onUp);

    if (!_state) return;
    var state = _state;
    _state = null;

    if (!state.moved) {
      state.group.removeAttribute("transform");
      // Single click → show selection / resize handles
      if (typeof CanvasSelect !== "undefined") {
        CanvasSelect.selectGroup(state.group, state.svg, state.patternId);
      }
      return;
    }
    // Drag completed — dismiss any open selection box
    if (typeof CanvasSelect !== "undefined") CanvasSelect.deselect();

    var dx = e.clientX - state.startClientX;
    var dy = e.clientY - state.startClientY;

    // Compute new percentage position (clamped to canvas bounds)
    var dxPct = (dx / state.svgRect.width) * 100;
    var dyPct = (dy / state.svgRect.height) * 100;
    var newX = Math.max(0, state.originXPct + dxPct).toFixed(2);
    var newY = Math.max(0, state.originYPct + dyPct).toFixed(2);

    // PATCH position and refresh canvas with clean re-render
    var formData = new FormData();
    formData.append("x", newX);
    formData.append("y", newY);

    // Route custom layers to /api/layers/ — /api/slots/ only handles template slots
    var dragUrl = state.slotId.startsWith("custom_")
      ? "/api/layers/" + state.patternId + "/" + state.slotId
      : "/api/slots/" + state.patternId + "/" + state.slotId + "/position";
    fetch(dragUrl, { method: "PATCH", body: formData })
      .then(function (r) {
        return r.ok ? r.text() : Promise.reject("HTTP " + r.status);
      })
      .then(function (html) {
        var canvas = document.getElementById("preview-canvas");
        if (canvas) {
          canvas.outerHTML = html;
          htmx.process(document.body);
          setTimeout(initCanvasInteractions, 50);
        }
      })
      .catch(function (err) {
        console.error("CanvasDrag: position sync failed:", err);
        // Revert visual transform so the slot snaps back
        state.group.removeAttribute("transform");
        BannerToast.show("error", "位置の保存に失敗しました。", "Drag Error");
      });
  }

  return { init: init };
})();

/* ==========================================================================
   Canvas Text Edit (double-click to edit text slots inline)
   ========================================================================== */

/**
 * CanvasTextEdit — double-click any text/button slot on the SVG canvas to
 * open a positioned <textarea> overlay for inline editing.
 *
 * Flow:
 *  1. dblclick on a .draggable-slot[data-slot-type=text|button|image_or_text]
 *  2. A <textarea> is rendered with `position:fixed`, sized and placed over
 *     the slot using getBoundingClientRect() (accounts for CSS zoom).
 *  3. blur or Enter  → PATCH /api/slots/{patternId}/{slotId}, canvas re-renders.
 *  4. Escape         → dismiss without saving.
 */
var CanvasTextEdit = (function () {
  var _TEXT_TYPES = ["text", "button", "image_or_text"];
  var _active = null; // { input, patternId, slotId, slotType }

  /** Attach dblclick listeners to text-type .draggable-slot groups. */
  function init() {
    var canvas = document.getElementById("preview-canvas");
    if (!canvas) return;

    var svg = canvas.querySelector("svg");
    if (!svg) return;

    var patternId = canvas.getAttribute("data-pattern-id");
    if (!patternId) return;

    svg.querySelectorAll("g.draggable-slot").forEach(function (group) {
      var slotType = group.getAttribute("data-slot-type");
      if (!_TEXT_TYPES.includes(slotType)) return;
      if (group.dataset.textEditInit === "1") return;
      group.dataset.textEditInit = "1";

      group.addEventListener("dblclick", function (e) {
        // Rule B: locked slots keep drag/resize but block inline text editing
        if (group.dataset.locked === "true") return;
        e.preventDefault();
        e.stopPropagation();
        _openOverlay(group, svg, patternId);
      });
    });
  }

  /** Open the textarea overlay positioned over the given slot group. */
  function _openOverlay(group, svg, patternId) {
    dismiss(); // close any existing overlay first

    var svgRect = svg.getBoundingClientRect();
    var xPct  = parseFloat(group.getAttribute("data-x") || "0");
    var yPct  = parseFloat(group.getAttribute("data-y") || "0");
    var wPct  = parseFloat(group.getAttribute("data-w") || "20");
    var hPct  = parseFloat(group.getAttribute("data-h") || "10");
    var slotId   = group.getAttribute("data-slot-id");
    var slotType = group.getAttribute("data-slot-type");

    // Screen-space position of the slot (fixed coordinates, zoom-aware)
    var left   = svgRect.left   + (xPct / 100) * svgRect.width;
    var top    = svgRect.top    + (yPct / 100) * svgRect.height;
    var width  = Math.max((wPct / 100) * svgRect.width,  48);
    var height = Math.max((hPct / 100) * svgRect.height, 24);

    // Read current text from the slot's <text> child (if any)
    var textEl = group.querySelector("text");
    var currentText = textEl ? (textEl.textContent || "") : "";

    // Build overlay textarea
    var ta = document.createElement("textarea");
    ta.value = currentText;

    var fontSize = Math.round(Math.max(11, height * 0.32));
    ta.setAttribute("style", [
      "position:fixed",
      "left:"   + left   + "px",
      "top:"    + top    + "px",
      "width:"  + width  + "px",
      "height:" + height + "px",
      "min-height:28px",
      "box-sizing:border-box",
      "margin:0",
      "padding:4px 6px",
      "border:2px solid #6366f1",
      "border-radius:4px",
      "background:rgba(255,255,255,0.96)",
      "color:#111",
      "font-size:" + fontSize + "px",
      "line-height:1.3",
      "text-align:center",
      "resize:none",
      "overflow:hidden",
      "outline:none",
      "z-index:9999",
      "box-shadow:0 0 0 3px rgba(99,102,241,0.25)",
    ].join(";"));

    document.body.appendChild(ta);
    _active = { input: ta, patternId: patternId, slotId: slotId, slotType: slotType };

    ta.focus();
    ta.select();

    ta.addEventListener("blur",    function () { _commit(); });
    ta.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); _commit(); }
      if (e.key === "Escape") { dismiss(); }
    });
  }

  /** Save the overlay value and refresh the canvas. */
  function _commit() {
    if (!_active) return;
    var o = _active;
    _active = null;

    var text = o.input.value; // preserve whitespace / newlines intentionally
    o.input.remove();

    // Immediately sync typed text to the AI tab prompt for this slot
    syncTextToAiTab(o.slotId, text);

    var formData = new FormData();
    formData.append("content", text);
    formData.append("slot_type", o.slotType === "button" ? "button" : "text");

    fetch("/api/slots/" + o.patternId + "/" + o.slotId, {
      method: "PATCH",
      body: formData,
    })
      .then(function (r) { return r.ok ? r.text() : Promise.reject("HTTP " + r.status); })
      .then(function (html) {
        var canvas = document.getElementById("preview-canvas");
        if (canvas) {
          canvas.outerHTML = html;
          htmx.process(document.body);
          setTimeout(initCanvasInteractions, 50);
        }
      })
      .catch(function (err) {
        console.error("CanvasTextEdit: save failed:", err);
        BannerToast.show("error", "テキストの保存に失敗しました。", "Edit Error");
      });
  }

  /** Dismiss any open overlay without saving. */
  function dismiss() {
    if (_active) {
      _active.input.remove();
      _active = null;
    }
  }

  return { init: init, dismiss: dismiss };
})();

/* ==========================================================================
   Canvas Selection & Resize Handles
   ========================================================================== */

/**
 * CanvasSelect — single-click a slot to show a bounding box with 8 resize
 * handles (corners + edges). Drag a handle to resize; on mouseup the new
 * geometry is PATCHed to /api/slots/{patternId}/{slotId}/position and the
 * canvas re-renders.
 *
 * Handle directions: nw · n · ne · e · se · s · sw · w
 * Left/top handles simultaneously update x/y to keep the anchor correct.
 */
var CanvasSelect = (function () {
  var HANDLE_PX = 8;
  var HALF = HANDLE_PX / 2;
  var DIRS = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
  var CURSORS = {
    nw: "nwse-resize", n: "ns-resize",  ne: "nesw-resize",
    e:  "ew-resize",   se: "nwse-resize", s: "ns-resize",
    sw: "nesw-resize", w:  "ew-resize",
  };

  var _sel    = null; // current selection state
  var _resize = null; // active resize drag state

  /* ── public ── */

  function init() {
    var canvas = document.getElementById("preview-canvas");
    if (!canvas) return;
    var svg = canvas.querySelector("svg");
    if (!svg || svg.dataset.selectInit === "1") return;
    svg.dataset.selectInit = "1";
    // Click on canvas background → deselect
    svg.addEventListener("click", function (e) {
      if (!e.target.closest("g.draggable-slot")) deselect();
    });
  }

  /** Show the selection overlay for a given slot group. */
  function selectGroup(group, svg, patternId) {
    deselect();

    var svgRect = svg.getBoundingClientRect();
    var xPct = parseFloat(group.getAttribute("data-x") || "0");
    var yPct = parseFloat(group.getAttribute("data-y") || "0");
    var wPct = parseFloat(group.getAttribute("data-w") || "10");
    var hPct = parseFloat(group.getAttribute("data-h") || "10");
    var slotId = group.getAttribute("data-slot-id");

    var overlay = _buildOverlay(svgRect, xPct, yPct, wPct, hPct);
    document.body.appendChild(overlay);

    overlay.querySelectorAll(".rh").forEach(function (handle) {
      handle.addEventListener("mousedown", function (e) {
        e.preventDefault();
        e.stopPropagation();
        _resize = {
          dir: handle.dataset.dir, overlay: overlay,
          svgRect: svgRect, slotId: slotId, patternId: patternId,
          startX: e.clientX, startY: e.clientY,
          ox: xPct, oy: yPct, ow: wPct, oh: hPct,
        };
        document.removeEventListener("mousedown", _outsideClick);
        document.addEventListener("mousemove", _onResizeMove);
        document.addEventListener("mouseup",    _onResizeUp);
      });
    });

    _sel = { overlay, group, svg, patternId, slotId, xPct, yPct, wPct, hPct };
    setTimeout(function () {
      document.addEventListener("mousedown", _outsideClick);
    }, 0);
  }

  function deselect() {
    document.removeEventListener("mousedown", _outsideClick);
    var ov = document.getElementById("canvas-sel-overlay");
    if (ov) ov.remove();
    _sel = null;
  }

  /* ── private helpers ── */

  function _buildOverlay(svgRect, xPct, yPct, wPct, hPct) {
    var div = document.createElement("div");
    div.id = "canvas-sel-overlay";
    _positionOverlay(div, svgRect, xPct, yPct, wPct, hPct);
    div.style.cssText += [
      "border:2px solid #6366f1",
      "box-sizing:border-box",
      "pointer-events:none",
      "z-index:10000",
    ].join(";");

    DIRS.forEach(function (dir) {
      var h = document.createElement("div");
      h.className = "rh";
      h.dataset.dir = dir;
      h.style.cssText = [
        "position:absolute",
        "width:" + HANDLE_PX + "px",
        "height:" + HANDLE_PX + "px",
        "background:#6366f1",
        "border:1.5px solid #fff",
        "border-radius:2px",
        "pointer-events:all",
        "cursor:" + CURSORS[dir],
        "z-index:10001",
        _handlePos(dir),
      ].join(";");
      div.appendChild(h);
    });

    return div;
  }

  function _handlePos(dir) {
    var m = -HALF + "px";
    var c = "calc(50% - " + HALF + "px)";
    var pos = {
      nw: "top:" + m + ";left:" + m,
      n:  "top:" + m + ";left:" + c,
      ne: "top:" + m + ";right:" + m,
      e:  "top:" + c + ";right:" + m,
      se: "bottom:" + m + ";right:" + m,
      s:  "bottom:" + m + ";left:" + c,
      sw: "bottom:" + m + ";left:" + m,
      w:  "top:" + c + ";left:" + m,
    };
    return pos[dir] || "";
  }

  function _positionOverlay(div, svgRect, xPct, yPct, wPct, hPct) {
    var l = svgRect.left + (xPct / 100) * svgRect.width;
    var t = svgRect.top  + (yPct / 100) * svgRect.height;
    var w = Math.max(4, (wPct / 100) * svgRect.width);
    var h = Math.max(4, (hPct / 100) * svgRect.height);
    div.style.cssText = [
      "position:fixed",
      "left:" + l + "px", "top:" + t + "px",
      "width:" + w + "px", "height:" + h + "px",
    ].join(";");
  }

  function _calcGeometry(r, clientX, clientY) {
    var dxPct = ((clientX - r.startX) / r.svgRect.width)  * 100;
    var dyPct = ((clientY - r.startY) / r.svgRect.height) * 100;
    var x = r.ox, y = r.oy, w = r.ow, h = r.oh;
    switch (r.dir) {
      case "nw": x=r.ox+dxPct; y=r.oy+dyPct; w=r.ow-dxPct; h=r.oh-dyPct; break;
      case "n":                 y=r.oy+dyPct;               h=r.oh-dyPct; break;
      case "ne":                y=r.oy+dyPct; w=r.ow+dxPct; h=r.oh-dyPct; break;
      case "e":                               w=r.ow+dxPct;               break;
      case "se":                              w=r.ow+dxPct; h=r.oh+dyPct; break;
      case "s":                                             h=r.oh+dyPct; break;
      case "sw": x=r.ox+dxPct;               w=r.ow-dxPct; h=r.oh+dyPct; break;
      case "w":  x=r.ox+dxPct;               w=r.ow-dxPct;               break;
    }
    return {
      x: Math.max(0,   x),
      y: Math.max(0,   y),
      w: Math.max(1.5, w),
      h: Math.max(1.5, h),
    };
  }

  function _onResizeMove(e) {
    if (!_resize) return;
    var g = _calcGeometry(_resize, e.clientX, e.clientY);
    _positionOverlay(_resize.overlay, _resize.svgRect, g.x, g.y, g.w, g.h);
  }

  function _onResizeUp(e) {
    document.removeEventListener("mousemove", _onResizeMove);
    document.removeEventListener("mouseup",   _onResizeUp);
    if (!_resize) return;
    var r = _resize;
    _resize = null;

    var g = _calcGeometry(r, e.clientX, e.clientY);
    deselect();

    var fd = new FormData();
    fd.append("x",      g.x.toFixed(2));
    fd.append("y",      g.y.toFixed(2));
    fd.append("width",  g.w.toFixed(2));
    fd.append("height", g.h.toFixed(2));

    // Route custom layers to /api/layers/ — /api/slots/ only handles template slots
    var resizeUrl = r.slotId.startsWith("custom_")
      ? "/api/layers/" + r.patternId + "/" + r.slotId
      : "/api/slots/" + r.patternId + "/" + r.slotId + "/position";
    fetch(resizeUrl, { method: "PATCH", body: fd })
      .then(function (res) { return res.ok ? res.text() : Promise.reject("HTTP " + res.status); })
      .then(function (html) {
        var canvas = document.getElementById("preview-canvas");
        if (!canvas) return;
        canvas.outerHTML = html;
        htmx.process(document.body);
        setTimeout(function () {
          initCanvasInteractions();
          // Re-select the resized slot so the user can keep adjusting
          var newCanvas = document.getElementById("preview-canvas");
          if (!newCanvas) return;
          var svg = newCanvas.querySelector("svg");
          var newGroup = svg && svg.querySelector('g[data-slot-id="' + r.slotId + '"]');
          if (newGroup) selectGroup(newGroup, svg, r.patternId);
        }, 50);
      })
      .catch(function (err) {
        console.error("CanvasSelect: resize save failed:", err);
        BannerToast.show("error", "サイズの保存に失敗しました。", "Resize Error");
      });
  }

  function _outsideClick(e) {
    var ov = document.getElementById("canvas-sel-overlay");
    if (ov && ov.contains(e.target)) return;
    if (e.target.closest && e.target.closest("g.draggable-slot")) return;
    deselect();
  }

  return { init: init, selectGroup: selectGroup, deselect: deselect };
})();

/* ==========================================================================
   Text → AI Tab Synchronization
   ========================================================================== */

/**
 * syncTextToAiTab(slotId, text)
 * Immediately copy a known text value into the AI tab's prompt field for that
 * slot. Called after canvas inline edit or manual-tab save.
 */
function syncTextToAiTab(slotId, text) {
  var el = document.getElementById("ai-prompt-" + slotId);
  if (el && text && text.trim()) {
    el.value = text.trim();
  }
}

/**
 * syncAllTextToAiTab()
 * Walk every slot <g> in the current SVG canvas and copy any actual content
 * (marked data-content="true") into the matching AI tab prompt textarea.
 * Called after canvas re-renders so the AI tab stays in sync automatically.
 */
function syncAllTextToAiTab() {
  var canvas = document.getElementById("preview-canvas");
  if (!canvas) return;
  var svg = canvas.querySelector("svg");
  if (!svg) return;
  svg.querySelectorAll("g.draggable-slot").forEach(function (group) {
    var slotId = group.getAttribute("data-slot-id");
    var textEl = group.querySelector('text[data-content="true"]');
    if (textEl && textEl.textContent.trim()) {
      syncTextToAiTab(slotId, textEl.textContent);
    }
  });
}

/* ==========================================================================
   Initialization
   ========================================================================== */

document.addEventListener("DOMContentLoaded", function () {
  initCharCounters(document);
  initDragDropZones(document);
  initCanvasInteractions();
});
