// Adaptive IDS website: mobile menu, optional links, and the evaluation-request form.
(function () {
  "use strict";
  var cfg = window.ADAPTIVE_IDS_SITE || {};

  // Mobile menu
  var btn = document.querySelector(".menu-btn");
  var nav = document.getElementById("site-nav");
  if (btn && nav) {
    btn.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.tagName === "A") { nav.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); }
    });
  }

  // Optional links and contact address from config.js
  function showLinks(kind, url) {
    if (!url) return;
    document.querySelectorAll('[data-link="' + kind + '"]').forEach(function (a) {
      a.href = url; a.hidden = false; a.rel = "noopener"; a.target = "_blank";
    });
  }
  showLinks("linkedin", cfg.linkedinUrl);
  showLinks("github", cfg.githubUrl);
  if (cfg.contactEmail) {
    document.querySelectorAll("[data-contact-email]").forEach(function (el) {
      var a = document.createElement("a");
      a.href = "mailto:" + cfg.contactEmail; a.textContent = cfg.contactEmail;
      el.replaceChildren(a);
    });
  }

  // Evaluation-request form
  var form = document.getElementById("eval-form");
  if (!form) return;
  var status = document.getElementById("form-status");
  var submit = form.querySelector('button[type="submit"]');
  var EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

  function say(text, kind) {
    status.textContent = text;
    status.className = "form-status" + (kind ? " " + kind : "");
  }
  function value(name) {
    var el = form.elements[name];
    return el ? String(el.value || "").trim() : "";
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    say("");
    if (value("website")) { say("Thank you. We'll be in touch.", "ok"); form.reset(); return; } // bot trap

    var data = {
      name: value("name"),
      email: value("email"),
      organisation: value("organisation"),
      role: value("role") || null,
      organisation_type: value("organisation_type"),
      interest: value("interest"),
      message: value("message") || null,
      consent: form.elements.consent.checked,
      source: "website",
    };
    var problems = [];
    if (data.name.length < 2) problems.push("your name");
    if (!EMAIL.test(data.email)) problems.push("a valid email address");
    if (data.organisation.length < 2) problems.push("your organisation");
    if (!data.organisation_type) problems.push("your organisation type");
    if (!data.consent) problems.push("your agreement to the privacy notice");
    if (problems.length) { say("Please add " + problems.join(", ") + ".", "err"); return; }
    if (!cfg.supabaseUrl || !cfg.supabasePublishableKey) { say("The form isn't configured yet. Please try again later.", "err"); return; }

    submit.disabled = true;
    say("Sending…");
    fetch(cfg.supabaseUrl + "/rest/v1/" + cfg.requestsTable, {
      method: "POST",
      headers: {
        apikey: cfg.supabasePublishableKey,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify(data),
    }).then(function (res) {
      if (res.ok) {
        form.reset();
        say("Thank you, your request has been sent. We'll reply within two working days.", "ok");
        return;
      }
      return res.json().catch(function () { return {}; }).then(function (body) {
        var msg = (body && body.message) || "";
        if (/too many requests|temporarily busy/i.test(msg)) say("We've already received a request from this address. Please wait a few minutes before sending another.", "err");
        else say("Sorry, that didn't go through. Please check the details and try again.", "err");
      });
    }).catch(function () {
      say("Sorry, we couldn't reach the server. Please check your connection and try again.", "err");
    }).finally(function () { submit.disabled = false; });
  });
})();
