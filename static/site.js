// Filters for the issues and decisions pages. The page works without this:
// every item is listed, and the filter bar stays hidden.
// Choices are kept in the address (?board=Select+Board&q=bridge) so a
// filtered view can be shared.
(function () {
  document.querySelectorAll("form[data-filter-target]").forEach(function (form) {
    var scope = document.querySelector('[data-filter-scope="' + form.dataset.filterTarget + '"]');
    if (!scope) return;
    var items = Array.prototype.slice.call(scope.querySelectorAll("[data-text]"));
    var count = form.querySelector(".filter-count");
    var empty = scope.querySelector(".filter-empty");
    var fields = Array.prototype.slice.call(form.elements).filter(function (el) { return el.name; });
    var params = new URLSearchParams(location.search);
    fields.forEach(function (el) { if (params.get(el.name)) el.value = params.get(el.name); });
    form.hidden = false;

    function apply() {
      var want = {};
      fields.forEach(function (el) { want[el.name] = el.value.trim(); });
      var words = (want.q || "").toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;
      items.forEach(function (it) {
        var ok = words.every(function (w) { return it.dataset.text.indexOf(w) !== -1; });
        ["board", "category", "result"].forEach(function (k) {
          if (ok && want[k] && it.dataset[k] !== want[k]) ok = false;
        });
        it.hidden = !ok;
        if (ok) shown++;
      });
      // Hide a section whose items are all filtered out.
      scope.querySelectorAll("section").forEach(function (sec) {
        var any = sec.querySelector("[data-text]:not([hidden])");
        sec.hidden = !any;
      });
      if (empty) empty.hidden = shown > 0;
      var filtering = fields.some(function (el) { return el.value.trim(); });
      // Open folded lists while filtering so matches in them show.
      scope.querySelectorAll("details").forEach(function (d) { if (filtering) d.open = true; });
      if (count) count.textContent = filtering ? shown + " of " + items.length : "";
      var next = new URLSearchParams();
      fields.forEach(function (el) { if (el.value.trim()) next.set(el.name, el.value.trim()); });
      var qs = next.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
    }
    form.addEventListener("input", apply);
    form.addEventListener("change", apply);  // older mobile Safari fires only change on <select>
    form.addEventListener("submit", function (e) { e.preventDefault(); apply(); });
    apply();
  });
})();
