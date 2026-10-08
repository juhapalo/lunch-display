/* Shows the configured pages one after another, each for its own duration.
 * The next page is loaded into a hidden iframe and swapped in once it has
 * loaded, so the screen never shows a blank page while loading. */
(function () {
  "use strict";

  var DEFAULT_ROTATION = [{ url: "dashboard", duration: 60, enabled: true }];
  var LOAD_TIMEOUT_MS = 15000;

  var frames = [document.getElementById("frame-a"), document.getElementById("frame-b")];
  var active = 0;
  var rotation = DEFAULT_ROTATION;
  var position = -1;
  var currentUrl = null;

  function getJSON(url, onSuccess, onError) {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", url, true);
    xhr.timeout = 10000;
    xhr.onload = function () {
      if (xhr.status === 200) {
        try { onSuccess(JSON.parse(xhr.responseText)); return; } catch (e) { /* fall through */ }
      }
      onError();
    };
    xhr.onerror = onError;
    xhr.ontimeout = onError;
    xhr.send();
  }

  function enabledItems(list) {
    var result = [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].enabled !== false) { result.push(list[i]); }
    }
    return result.length ? result : DEFAULT_ROTATION;
  }

  function resolveUrl(url) {
    return url === "dashboard" ? "/dashboard" : url;
  }

  function show(url, done) {
    // Keep a single page on screen if nothing else is configured.
    if (url === currentUrl && rotation.length === 1) { done(); return; }
    var next = frames[1 - active];
    var finished = false;
    var swap = function () {
      if (finished) { return; }
      finished = true;
      clearTimeout(timer);
      next.className = "active";
      frames[active].className = "";
      var old = frames[active];
      active = 1 - active;
      currentUrl = url;
      // Free memory used by the previous page (important on a Pi 1B).
      setTimeout(function () { old.src = "about:blank"; }, 1000);
      done();
    };
    var timer = setTimeout(swap, LOAD_TIMEOUT_MS);
    next.onload = function () {
      if (next.getAttribute("data-url") === url) { swap(); }
    };
    next.setAttribute("data-url", url);
    next.src = url;
  }

  function step() {
    getJSON("/api/rotation", function (data) {
      rotation = enabledItems(data.rotation || []);
      advance();
    }, function () {
      advance();
    });
  }

  function advance() {
    position = (position + 1) % rotation.length;
    var item = rotation[position];
    var duration = Math.max(5, parseInt(item.duration, 10) || 60) * 1000;
    show(resolveUrl(item.url), function () {
      setTimeout(step, duration);
    });
  }

  step();
})();
