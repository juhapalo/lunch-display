(function () {
  "use strict";

  var rows = document.getElementById("rows");
  var message = document.getElementById("message");

  function setMessage(text, ok) {
    message.textContent = text;
    message.className = ok ? "ok" : "fail";
  }

  function request(method, url, body, callback) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    if (body !== null) { xhr.setRequestHeader("Content-Type", "application/json"); }
    xhr.onload = function () {
      var data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
      callback(xhr.status, data);
    };
    xhr.onerror = function () { callback(0, {}); };
    xhr.send(body === null ? null : JSON.stringify(body));
  }

  function addRow(item) {
    var tr = document.createElement("tr");

    var enabledTd = document.createElement("td");
    var enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.className = "enabled";
    enabled.checked = item.enabled !== false;
    enabledTd.appendChild(enabled);

    var urlTd = document.createElement("td");
    var url = document.createElement("input");
    url.type = "text";
    url.className = "url";
    url.placeholder = "https://… tai dashboard";
    url.value = item.url || "";
    urlTd.appendChild(url);

    var durationTd = document.createElement("td");
    var duration = document.createElement("input");
    duration.type = "number";
    duration.className = "duration";
    duration.min = 5;
    duration.value = item.duration || 30;
    durationTd.appendChild(duration);

    var actionsTd = document.createElement("td");
    var buttons = [
      ["↑", function () { if (tr.previousSibling) { rows.insertBefore(tr, tr.previousSibling); } }],
      ["↓", function () { if (tr.nextSibling) { rows.insertBefore(tr.nextSibling, tr); } }],
      ["Poista", function () { rows.removeChild(tr); }]
    ];
    for (var i = 0; i < buttons.length; i++) {
      var button = document.createElement("button");
      button.textContent = buttons[i][0];
      button.onclick = buttons[i][1];
      actionsTd.appendChild(button);
    }

    tr.appendChild(enabledTd);
    tr.appendChild(urlTd);
    tr.appendChild(durationTd);
    tr.appendChild(actionsTd);
    rows.appendChild(tr);
  }

  function collect() {
    var result = [];
    var trs = rows.getElementsByTagName("tr");
    for (var i = 0; i < trs.length; i++) {
      result.push({
        url: trs[i].querySelector(".url").value.trim(),
        duration: parseInt(trs[i].querySelector(".duration").value, 10),
        enabled: trs[i].querySelector(".enabled").checked
      });
    }
    return result;
  }

  function load() {
    request("GET", "/api/rotation", null, function (status, data) {
      rows.innerHTML = "";
      var list = data.rotation || [];
      for (var i = 0; i < list.length; i++) { addRow(list[i]); }
    });
  }

  document.getElementById("add").onclick = function () { addRow({ url: "", duration: 30 }); };

  document.getElementById("save").onclick = function () {
    request("POST", "/api/rotation", { rotation: collect() }, function (status, data) {
      if (status === 200) {
        setMessage("Tallennettu. Muutokset näkyvät seuraavalla sivunvaihdolla.", true);
      } else {
        setMessage("Virhe: " + (data.error || status), false);
      }
    });
  };

  document.getElementById("refresh").onclick = function () {
    request("POST", "/api/refresh", {}, function (status, data) {
      setMessage(status === 200 ? "Päivitys käynnistetty." : "Virhe: " + (data.error || status), status === 200);
    });
  };

  load();
})();
