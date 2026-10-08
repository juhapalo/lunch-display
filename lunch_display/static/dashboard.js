(function () {
  "use strict";

  var DAYS = ["sunnuntai", "maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai"];
  var REFRESH_MS = 60000;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  function tickClock() {
    var now = new Date();
    document.getElementById("clock").textContent = pad(now.getHours()) + ":" + pad(now.getMinutes());
    document.getElementById("date").textContent =
      DAYS[now.getDay()] + " " + now.getDate() + "." + (now.getMonth() + 1) + "." + now.getFullYear();
  }

  function temp(value) {
    return value === null || value === undefined ? "–" : value + "°";
  }

  function renderWeather(weather, error) {
    document.getElementById("weather-error").textContent = error || "";
    if (!weather) { return; }
    var current = weather.current || {};
    document.getElementById("weather-title").textContent = "Sää – " + (weather.location || "");
    document.getElementById("weather-icon").textContent = current.icon || "";
    document.getElementById("weather-temp").textContent = temp(current.temperature);
    var text = current.description || "";
    if (current.feels_like !== null && current.feels_like !== undefined) {
      text += " · tuntuu " + temp(current.feels_like);
    }
    if (current.wind !== null && current.wind !== undefined) {
      text += " · tuuli " + Math.round(current.wind) + " m/s";
    }
    document.getElementById("weather-text").textContent = text;

    var today = weather.today;
    document.getElementById("weather-today").textContent = today
      ? "Tänään " + temp(today.min) + " … " + temp(today.max) +
        (today.sunrise ? " · ☀ " + today.sunrise + "–" + today.sunset : "")
      : "";

    var hours = document.getElementById("weather-hours");
    hours.innerHTML = "";
    var list = weather.hours || [];
    for (var i = 0; i < list.length; i++) {
      var row = el("div", "hour");
      row.appendChild(el("span", "time", list[i].time));
      row.appendChild(el("span", "icon", list[i].icon));
      row.appendChild(el("span", "temp", temp(list[i].temperature)));
      var rain = list[i].precipitation_probability;
      row.appendChild(el("span", "rain", rain === null || rain === undefined ? "" : rain + "%"));
      hours.appendChild(row);
    }
  }

  function renderMenus(menus) {
    var container = document.getElementById("menus");
    container.innerHTML = "";
    for (var i = 0; i < menus.length; i++) {
      var menu = menus[i];
      var panel = el("section", "panel menu");
      panel.appendChild(el("h2", null, menu.name));
      if (menu.items && menu.items.length) {
        var ul = el("ul");
        for (var j = 0; j < menu.items.length; j++) {
          ul.appendChild(el("li", null, menu.items[j]));
        }
        panel.appendChild(ul);
      } else {
        panel.appendChild(el("div", "error", menu.error || "Ei ruokalistaa"));
      }
      container.appendChild(panel);
    }
  }

  function load() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/data", true);
    xhr.timeout = 10000;
    xhr.onload = function () {
      if (xhr.status !== 200) { return; }
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (e) { return; }
      renderWeather(data.weather, data.weather_error);
      renderMenus(data.menus || []);
      var updated = data.updated ? new Date(data.updated * 1000) : null;
      document.getElementById("status").textContent = updated
        ? "Päivitetty " + pad(updated.getHours()) + ":" + pad(updated.getMinutes())
        : "Haetaan tietoja…";
    };
    xhr.send();
  }

  tickClock();
  setInterval(tickClock, 1000);
  load();
  setInterval(load, REFRESH_MS);
})();
