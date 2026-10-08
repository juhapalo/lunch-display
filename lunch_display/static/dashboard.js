(function () {
  "use strict";

  var DAYS = ["sunnuntai", "maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai"];
  var REFRESH_MS = 60000;
  var clockOffset = null;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  function tickClock() {
    if (clockOffset === null) { return; }
    var now = new Date(new Date().getTime() + clockOffset);
    document.getElementById("clock").textContent = pad(now.getUTCHours()) + ":" + pad(now.getUTCMinutes());
    document.getElementById("date").textContent =
      DAYS[now.getUTCDay()] + " " + now.getUTCDate() + "." + (now.getUTCMonth() + 1) + "." + now.getUTCFullYear();
  }

  function syncClock(value) {
    var parts = value && value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
    if (!parts) { return; }
    clockOffset = Date.UTC(+parts[1], +parts[2] - 1, +parts[3], +parts[4], +parts[5], +parts[6]) -
      new Date().getTime();
    tickClock();
  }

  function menuDate(value, todayValue) {
    var parts = value && value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!parts) { return ""; }
    var date = new Date(Date.UTC(+parts[1], +parts[2] - 1, +parts[3]));
    var label = DAYS[date.getUTCDay()] + " " + (+parts[3]) + "." + (+parts[2]) + ".";
    var todayParts = todayValue && todayValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (todayParts) {
      var tomorrow = new Date(Date.UTC(+todayParts[1], +todayParts[2] - 1, +todayParts[3]));
      tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
      if (date.getTime() === tomorrow.getTime()) {
        return "Lounas huomenna – " + label;
      }
    }
    return "Lounas " + label;
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

  function renderMenus(menus, targetDate, todayDate) {
    var container = document.getElementById("menus");
    container.innerHTML = "";
    for (var i = 0; i < menus.length; i++) {
      var menu = menus[i];
      var panel = el("section", "panel menu");
      panel.appendChild(el("h2", null, menu.name));
      panel.appendChild(el("div", "menu-date", menuDate(targetDate, todayDate)));
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
      syncClock(data.local_time);
      renderMenus(data.menus || [], data.menus_date, data.date);
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
