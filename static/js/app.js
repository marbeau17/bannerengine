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
 * After every htmx swap, re-initialize dynamic components inside the
 * swapped fragment (e.g. char counters, drag-drop zones).
 */
document.body.addEventListener("htmx:afterSwap", function (event) {
  var target = event.detail.target;

  // Re-bind character counters inside the swapped region
  initCharCounters(target);

  // Re-bind drag-drop zones inside the swapped region
  initDragDropZones(target);

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
   Initialization
   ========================================================================== */

document.addEventListener("DOMContentLoaded", function () {
  initCharCounters(document);
  initDragDropZones(document);
});
