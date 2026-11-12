(function () {
  'use strict';
  // >>> Set this to your real inbox. The demo form opens the visitor's mail app (no backend needed).
  var CONTACT_EMAIL = 'hello@yaan.example';

  // >>> Login currently shows a "coming soon" page. When the app is live, set this to its login URL (e.g. https://app.yourdomain.com/login).
  var LOGIN_URL = 'coming-soon.html';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var icon = function (n) { return '<svg class="ic"><use href="#i-' + n + '"/></svg>'; };
  var li = function (arr) { return arr.map(function (t) { return '<li>' + icon('check') + '<span>' + t + '</span></li>'; }).join(''); };

  $$('[data-login]').forEach(function (a) { a.href = LOGIN_URL; });

  /* ---------- nav ---------- */
  var nav = $('#nav'), links = $('#links'), burger = $('#burger');
  window.addEventListener('scroll', function () { nav.classList.toggle('scrolled', window.scrollY > 8); }, { passive: true });
  burger.addEventListener('click', function () {
    var o = links.classList.toggle('open'); burger.setAttribute('aria-expanded', o);
  });
  $$('a', links).forEach(function (a) { a.addEventListener('click', function () { links.classList.remove('open'); burger.setAttribute('aria-expanded', false); }); });
  $('#yr').textContent = new Date().getFullYear();

  /* ---------- scroll reveal + counters ---------- */
  var io = 'IntersectionObserver' in window ? new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      e.target.classList.add('in'); io.unobserve(e.target);
      if (e.target.id === 'dash') animateDash();
    });
  }, { threshold: .15 }) : null;
  $$('.reveal').forEach(function (el) { io ? io.observe(el) : el.classList.add('in'); });

  /* ---------- hero trip card cycle ---------- */
  var statuses = ['Awaiting assignment', 'Assigned', 'Assigned', 'In progress', 'Completed'];
  var foots = [
    'Nothing reserved yet. Nobody notified.',
    'Driver &amp; vehicle checked for availability and capacity.',
    'Driver and employees notified. Each employee has a 4-digit OTP.',
    'Driver is on the way. Operator sees live status.',
    'All 4 employees OTP-verified. Trip closed.'
  ];
  var cur = 0;
  function tripStep(n) {
    $$('#tcSteps li').forEach(function (l, i) { l.classList.toggle('done', i <= n); });
    var s = $('#tcStatus'); s.textContent = statuses[n]; s.className = 'status' + (n ? ' s' + (n === 2 ? 1 : n) : '');
    $('#tcBar').style.width = (6 + n * 23.5) + '%';
    $('#tcFoot').innerHTML = foots[n];
  }
  tripStep(0);
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduce) setInterval(function () { cur = (cur + 1) % 5; tripStep(cur); }, 2400);
  else tripStep(4);

  /* ---------- stepper ---------- */
  var steps = [
    { t: 'Request', who: 'Operator', h: 'Operator raises a trip request', p: 'Pick the customer, site, time, employees and addresses. No driver or vehicle needed — the request just waits for the vendor.',
      b: ['Nothing is reserved and nobody is notified yet', 'Edit or cancel freely while it awaits assignment', 'Employees pulled from your own customer\'s list'],
      m: [['Customer', 'Acme Corp'], ['Shift', 'Night · 10:00 PM'], ['Employees', '4'], ['Status', '<span class="tag w">Awaiting assignment</span>']] },
    { t: 'Assign', who: 'Vendor Admin', h: 'Vendor assigns driver &amp; vehicle', p: 'Yaan shows only the drivers and vehicles that are genuinely free and big enough. Assign, and everyone is notified at once.',
      b: ['Blocks double-booking, even for simultaneous clicks', 'Capacity check incl. escort seat when needed', 'Can reject a request with a reason'],
      m: [['Driver', 'R. Kumar'], ['Vehicle', 'KA-01-AB-1234 · 7 seats'], ['Buffer check', '<span class="tag">30 min OK</span>'], ['Status', '<span class="tag i">Assigned</span>']] },
    { t: 'Ride &amp; verify', who: 'Driver + Employee', h: 'Drop-offs confirmed with OTP', p: 'Employees receive an OTP by SMS and/or email. At each drop, the driver enters it. No OTP, no silent drop — a reason is required.',
      b: ['Trip can end only when all employees are verified or flagged', 'Wrong-code attempts are limited', 'Exceptions surface on the dashboard'],
      m: [['Priya S.', '<span class="tag">Verified</span>'], ['Arjun M.', '<span class="tag">Verified</span>'], ['Neha R.', '<span class="tag w">Not dropped · reason</span>'], ['Trip', '<span class="tag i">Can end</span>']] },
    { t: 'Track &amp; report', who: 'Admins', h: 'Dashboard, compliance and expenses', p: 'See on-time performance, utilization and SMS delivery. Keep documents current and log every expense, then export to Excel.',
      b: ['Filter by customer, shift, vendor and date', 'Licence/insurance expiry warnings', 'Full audit trail; trips are never hard-deleted'],
      m: [['On-time', '94%'], ['Seat utilization', '78%'], ['Docs expiring (30d)', '<span class="tag w">3</span>'], ['Export', '<span class="tag">Excel</span>']] }
  ];
  var sTabs = $('#stepTabs'), sPanel = $('#stepPanel');
  steps.forEach(function (s, i) {
    var b = document.createElement('button');
    b.className = 'step-tab'; b.setAttribute('role', 'tab');
    b.innerHTML = '<span class="n">' + (i + 1) + '</span><span>' + s.t + '</span>';
    b.onclick = function () { showStep(i); };
    sTabs.appendChild(b);
  });
  function showStep(i) {
    var s = steps[i];
    $$('.step-tab', sTabs).forEach(function (b, k) { b.classList.toggle('on', k === i); b.setAttribute('aria-selected', k === i); });
    sPanel.innerHTML = '<div><span class="who">' + s.who + '</span><h3>' + s.h + '</h3><p class="muted">' + s.p + '</p><ul>' + li(s.b) + '</ul></div>' +
      '<div class="mock">' + s.m.map(function (r) { return '<div class="row"><span>' + r[0] + '</span><b>' + r[1] + '</b></div>'; }).join('') + '</div>';
  }
  showStep(0);

  /* ---------- roles ---------- */
  var roles = [
    { n: 'Operator', ic: 'users', d: 'Works for one customer and requests trips for its employees.',
      do: ['Add and edit employees', 'Request trips in minutes', 'See each employee\'s OTP beside their name', 'Track status of every request'],
      gain: ['No more calling the vendor for updates', 'Proof that each employee was dropped', 'Only your customer\'s data, nothing else'] },
    { n: 'Vendor Admin', ic: 'bus', d: 'Runs the fleet and assigns work for their own vendor.',
      do: ['Assign available drivers and vehicles', 'Create operators and drivers', 'Manage compliance documents and expenses', 'Choose SMS / email channels'],
      gain: ['Conflicts blocked automatically', 'Document expiry never a surprise', 'Fleet utilization visible at a glance'] },
    { n: 'Driver', ic: 'cal', d: 'Sees assigned trips and closes them with proof.',
      do: ['View assigned trips and instructions', 'Start the trip and enter OTPs at each drop', 'Mark "not dropped" with a reason', 'Log expenses (fuel, tolls…)'],
      gain: ['Clear schedule, fewer calls', 'Protected by verified drop records', 'Simple, task-focused screens'] }
  ];
  var rTabs = $('#roleTabs'), rBody = $('#roleBody');
  roles.forEach(function (r, i) {
    var b = document.createElement('button');
    b.className = 'role-tab'; b.setAttribute('role', 'tab'); b.innerHTML = icon(r.ic) + r.n;
    b.onclick = function () { showRole(i); }; rTabs.appendChild(b);
  });
  function showRole(i) {
    var r = roles[i];
    $$('.role-tab', rTabs).forEach(function (b, k) { b.classList.toggle('on', k === i); b.setAttribute('aria-selected', k === i); });
    rBody.innerHTML = '<h3>' + r.n + '</h3><p class="muted">' + r.d + '</p><div class="cols2"><div><h4>What you do</h4><ul>' + li(r.do) +
      '</ul></div><div class="gain"><h4>How it helps you</h4><ul>' + li(r.gain) + '</ul></div></div>';
  }
  showRole(0);

  /* ---------- OTP demo ---------- */
  var DEMO_OTP = '4821', tries = 5, locked = false, done = false;
  var boxes = $$('#otpBoxes input'), msg = $('#otpMsg');
  boxes.forEach(function (b, i) {
    b.addEventListener('input', function () {
      b.value = b.value.replace(/\D/g, '').slice(0, 1);
      if (b.value && boxes[i + 1]) boxes[i + 1].focus();
    });
    b.addEventListener('keydown', function (e) { if (e.key === 'Backspace' && !b.value && boxes[i - 1]) boxes[i - 1].focus(); if (e.key === 'Enter') $('#otpGo').click(); });
  });
  function say(t, c) { msg.textContent = t; msg.className = 'otp-msg ' + (c || ''); }
  $('#otpGo').onclick = function () {
    if (done) return;
    if (locked) { say('OTP locked. Mark the employee "not dropped" with a reason.', 'err'); return; }
    var v = boxes.map(function (b) { return b.value; }).join('');
    if (v.length < 4) { say('Enter all 4 digits.', 'err'); return; }
    if (v === DEMO_OTP) {
      done = true; say('✓ Priya S. verified. All employees accounted for.', 'ok');
      $('#otpEnd').disabled = false; $('#otpTries').textContent = 'Verified';
    } else {
      tries--; var w = $('#otpBoxes'); w.classList.remove('shake'); void w.offsetWidth; w.classList.add('shake');
      if (tries <= 0) { locked = true; $('#otpTries').textContent = 'Locked'; say('Too many wrong tries. OTP locked.', 'err'); }
      else { $('#otpTries').textContent = tries + ' tr' + (tries === 1 ? 'y' : 'ies') + ' left'; say('Wrong OTP. Ask the employee again.', 'err'); }
    }
  };
  $('#otpHint').onclick = function () { say('Demo OTP: ' + DEMO_OTP + ' (in real life only the Operator sees it)'); };
  $('#otpEnd').onclick = function () { say('Trip ended. Everything logged.', 'ok'); };

  /* ---------- features ---------- */
  var feats = [
    ['Operations', 'cal', 'Trip requests &amp; assignment', 'Operators request, vendors assign. Clear statuses from awaiting to completed.'],
    ['Operations', 'bus', 'Vehicles &amp; drivers', 'Maintain your fleet and driver roster with capacity and availability in one place.'],
    ['Operations', 'users', 'Employees, sites &amp; shifts', 'Addresses with coordinates, shifts and sites — everything needed for accurate pickups.'],
    ['Operations', 'pin', 'Trip map view', 'See pickup and drop points on a map for any trip.'],
    ['Safety', 'shield', 'Drop-off OTP', 'Every employee confirmed at their drop point, or flagged with a reason.'],
    ['Safety', 'msg', 'SMS &amp; email alerts', 'Drivers and employees are notified automatically — failed messages can be retried.'],
    ['Safety', 'lock', 'Vendor data isolation', 'Role-based access; each vendor sees only its own data on every request.'],
    ['Compliance', 'doc', 'Document tracking', 'Licence, insurance and permit expiry with a configurable early-warning window.'],
    ['Compliance', 'clock', 'Availability rules', '30-minute buffer and capacity checks prevent conflicts automatically.'],
    ['Compliance', 'check', 'Audit trail', 'Append-only history. Trips are cancelled, never deleted.'],
    ['Insights', 'chart', 'Live dashboard', 'On-time performance, utilization, trips by customer, shift and vendor.'],
    ['Insights', 'wallet', 'Expenses', 'Drivers and staff log expenses; admins see summaries and export to Excel.'],
    ['Insights', 'doc', 'Reports &amp; export', 'Download reports to Excel for finance and reviews.']
  ];
  var cats = ['All'].concat(feats.map(function (f) { return f[0]; }).filter(function (v, i, a) { return a.indexOf(v) === i; }));
  var chips = $('#chips'), grid = $('#featGrid');
  cats.forEach(function (c) {
    var b = document.createElement('button'); b.className = 'chip'; b.textContent = c; b.setAttribute('role', 'tab');
    b.onclick = function () { showFeats(c); }; chips.appendChild(b);
  });
  function showFeats(c) {
    $$('.chip', chips).forEach(function (b) { b.classList.toggle('on', b.textContent === c); });
    grid.innerHTML = feats.filter(function (f) { return c === 'All' || f[0] === c; }).map(function (f) {
      return '<div class="card feat"><div class="ico">' + icon(f[1]) + '</div><h3>' + f[2] + '</h3><p>' + f[3] + '</p></div>';
    }).join('');
  }
  showFeats('All');

  /* ---------- rule checker ---------- */
  function check() {
    var seats = +$('#chkSeats').value, pax = +$('#chkPax').value, fem = $('#chkFemale').checked, gap = +$('#chkGap').value;
    $('#chkPaxVal').textContent = pax;
    var need = pax + (fem ? 1 : 0), probs = [];
    if (need > seats) probs.push('Needs ' + need + ' seats (' + pax + ' passengers' + (fem ? ' + 1 escort' : '') + ') but vehicle has ' + seats + '.');
    if (gap < 30) probs.push('Driver\'s previous trip ended only ' + gap + ' min before pickup — 30 min buffer required.');
    var o = $('#chkOut');
    if (probs.length) { o.className = 'verdict no'; o.innerHTML = '✕ Assignment blocked<ul>' + probs.map(function (p) { return '<li>' + p + '</li>'; }).join('') + '</ul>'; }
    else { o.className = 'verdict ok'; o.innerHTML = '✓ Assignment allowed — ' + need + ' of ' + seats + ' seats used, buffer respected.'; }
  }
  $$('#chkSeats,#chkPax,#chkFemale,#chkGap').forEach(function (e) { e.addEventListener('input', check); });
  check();

  /* ---------- dashboard preview ---------- */
  var hourly = [['6', 8], ['7', 22], ['8', 30], ['9', 18], ['10', 9], ['12', 6], ['15', 11], ['17', 26], ['18', 34], ['19', 20], ['21', 14], ['22', 24]];
  var drivers = [['R. Kumar', 92], ['S. Das', 81], ['A. Khan', 74], ['M. Roy', 63], ['P. Singh', 51]];
  var dashDone = false;
  function animateDash() {
    if (dashDone) return; dashDone = true;
    var cols = $('#colsChart'), bars = $('#barsChart');
    cols.innerHTML = hourly.map(function (h) { return '<div data-t="' + h[0] + ':00 · ' + h[1] + ' trips" style="--h:' + h[1] + '"></div>'; }).join('');
    bars.innerHTML = drivers.map(function (d) { return '<div class="bar"><span>' + d[0] + '</span><i><u data-w="' + d[1] + '"></u></i><b>' + d[1] + '</b></div>'; }).join('');
    requestAnimationFrame(function () { requestAnimationFrame(function () {
      $$('div', cols).forEach(function (c) { c.style.height = (c.style.getPropertyValue('--h') / 36 * 100) + '%'; });
      $$('u', bars).forEach(function (u) { u.style.width = u.dataset.w + '%'; });
    }); });
    $$('[data-count]').forEach(function (el) {
      var to = +el.dataset.count, suf = el.dataset.suffix || '', t0 = performance.now();
      (function tick(t) { var p = Math.min((t - t0) / 900, 1); el.textContent = Math.round(to * p) + suf; if (p < 1) requestAnimationFrame(tick); })(t0);
    });
  }

  /* ---------- calculator ---------- */
  function calc() {
    var t = +$('#cTrips').value, m = +$('#cMin').value, p = +$('#cPct').value, d = +$('#cDays').value;
    $('#cTripsV').textContent = t; $('#cMinV').textContent = m; $('#cPctV').textContent = p + '%'; $('#cDaysV').textContent = d;
    var hrs = Math.round(t * m * (p / 100) * d / 60);
    $('#cHours').textContent = hrs.toLocaleString();
    $('#cNote').textContent = '≈ ' + (hrs / 8).toFixed(1) + ' working days of coordination effort per month, freed for things that need a human.';
  }
  $$('#cTrips,#cMin,#cPct,#cDays').forEach(function (e) { e.addEventListener('input', calc); });
  calc();

  /* ---------- FAQ ---------- */
  var faqs = [
    ['Who can use Yaan?', 'Companies that move employees across shifts, and the transport vendors that serve them. There are three roles: Vendor Admin, Operator and Driver — each sees only what they need.'],
    ['How do employees know their trip is confirmed?', 'Only after a Vendor Admin assigns a driver and vehicle do the driver and employees receive an SMS (and/or email, depending on your settings), including each employee\'s drop-off OTP.'],
    ['What if an employee can\'t share their OTP?', 'After 5 wrong tries the OTP locks. The driver marks that employee "not dropped" with a reason, which is flagged on the trip and the dashboard — so the trip can still be closed honestly.'],
    ['Can the same driver or vehicle be double-booked?', 'No. Yaan enforces a 30-minute buffer between trips at the database level, so even two admins assigning at the same moment can\'t create a conflict.'],
    ['Is our data separate from other vendors\'?', 'Yes. Vendor isolation is enforced by the API on every request, and deactivating a vendor locks out all of its users immediately.'],
    ['Do you track vehicle documents?', 'Yes — document types and expiry dates are recorded, with a configurable "about to expire" window (default 30 days) so renewals aren\'t missed.'],
    ['Can we export data?', 'Yes. Reports and expense summaries can be exported to Excel.']
  ];
  var fl = $('#faqList');
  faqs.forEach(function (f, i) {
    var d = document.createElement('div'); d.className = 'q';
    d.innerHTML = '<button aria-expanded="false" aria-controls="a' + i + '">' + f[0] + '</button><div class="a" id="a' + i + '"><div><p>' + f[1] + '</p></div></div>';
    d.firstChild.onclick = function () { var o = d.classList.toggle('open'); d.firstChild.setAttribute('aria-expanded', o); };
    fl.appendChild(d);
  });

  /* ---------- lead form (opens the visitor's email app) ---------- */
  $('#leadForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target, m = $('#formMsg'), n = f.name.value.trim(), em = f.email.value.trim();
    if (!n || !/^\S+@\S+\.\S+$/.test(em)) { m.className = 'form-msg err'; m.textContent = 'Please enter your name and a valid email.'; return; }
    var body = 'Name: ' + n + '\nEmail: ' + em + '\nType: ' + f.type.value + '\nTrips/day: ' + (f.trips.value || '—');
    window.location.href = 'mailto:' + CONTACT_EMAIL + '?subject=' + encodeURIComponent('Yaan demo request') + '&body=' + encodeURIComponent(body);
    m.className = 'form-msg ok'; m.textContent = 'Opening your email app to send the request…';
  });
})();
