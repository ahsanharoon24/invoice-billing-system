// Invoice & Billing System — small UI helpers
(function () {
  // today's date in topbar
  var el = document.getElementById('today-label');
  if (el) {
    el.textContent = new Date().toLocaleDateString('en-GB', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
    });
  }
})();
