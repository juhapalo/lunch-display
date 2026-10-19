/* Shows the configured pages one after another, each for its own duration.
 * Every page is loaded once into its own iframe that stays alive; a page
 * change only switches which iframe is visible, so pages are not reloaded at
 * every page change. Pages with a "refresh" interval (seconds) are reloaded
 * periodically, while hidden when other pages exist.
 * (The Pi's Chromium kiosk does the same with real tabs, see tabs.py.) */
(function () {
  "use strict";

  var DEFAULT_ROTATION = [{ url: "dashboard", duration: 60, enabled: true }];
  var REFRESH_CHECK_MS = 5000;

  var container = document.getElementById("frames");
  var frames = {};    // resolved url -> { el: iframe, loaded: ms }
  var refresh = {};   // resolved url -> refresh interval in seconds
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

  function frameCount() {
    var count = 0;
    for (var url in frames) {
      if (Object.prototype.hasOwnProperty.call(frames, url)) { count++; }
    }
    return count;
  }

  // Create an iframe for every new page and remove the ones no longer used.
  function sync(items) {
    var wanted = {};
    var intervals = {};
    var url, i;
    for (i = 0; i < items.length; i++) {
      url = resolveUrl(items[i].url);
      wanted[url] = true;
      var seconds = parseInt(items[i].refresh, 10) || 0;
      if (seconds > 0 && (!intervals[url] || seconds < intervals[url])) { intervals[url] = seconds; }
    }
    refresh = intervals;
    for (url in frames) {
      if (Object.prototype.hasOwnProperty.call(frames, url) && !wanted[url]) {
        container.removeChild(frames[url].el);
        delete frames[url];
      }
    }
    for (url in wanted) {
      if (Object.prototype.hasOwnProperty.call(wanted, url) && !frames[url]) {
        var el = document.createElement("iframe");
        el.title = "page";
        el.src = url;
        container.appendChild(el);
        frames[url] = { el: el, loaded: Date.now() };
      }
    }
  }

  function show(url) {
    for (var key in frames) {
      if (Object.prototype.hasOwnProperty.call(frames, key)) {
        frames[key].el.className = key === url ? "active" : "";
      }
    }
    currentUrl = url;
  }

  function refreshDue() {
    var now = Date.now();
    var count = frameCount();
    for (var url in frames) {
      if (!Object.prototype.hasOwnProperty.call(frames, url)) { continue; }
      var seconds = refresh[url];
      var entry = frames[url];
      if (!seconds || now - entry.loaded < seconds * 1000) { continue; }
      // Reload hidden pages only, so nobody sees the page reloading.
      if (url === currentUrl && count > 1) { continue; }
      entry.loaded = now;
      entry.el.src = url;
    }
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
    sync(rotation);
    show(resolveUrl(item.url));
    setTimeout(step, duration);
  }

  setInterval(refreshDue, REFRESH_CHECK_MS);
  step();
})();
