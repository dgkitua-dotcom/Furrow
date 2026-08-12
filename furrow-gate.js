/* ============================================================================
   FURROW subscription gate  —  furrow-gate.js
   Single-file access wall for the static site. Include on every page with:
       <script src="furrow-gate.js"></script>
   just before </body>.

   WHAT IT DOES
   - Keeps the nav and the live price ticker free and sharp.
   - Blurs everything else and shows a login / register overlay until unlocked.
   - Remembers the unlock for the browser session (sessionStorage) so the user
     is not re-gated as they move between pages.
   - Register form composes an email to you (mailto) with client + business
     details and an optional quotation request.

   SECURITY NOTE (read once)
   - This is a static site: this file is downloaded by the browser, so a
     determined technical user can read it. Passwords are stored here only as
     SHA-256 hashes (not plain text), which stops casual snooping but is NOT a
     server-grade secret. Treat this as a paywall that stops ordinary visitors,
     not as a vault. Move to a real backend when subscriptions become revenue.

   CHANGE PASSWORDS
   - Open hashgen.html, type a new password, copy the generated line, and paste
     it over the matching line below. Commit & push. Done.
   ============================================================================ */

(function () {
  "use strict";

  /* ---- CONFIG : replace these two lines using hashgen.html ---------------- */
  const SUBSCRIBER_HASH = "8600c3a403bbb972fe7f99e9194572057be4da9816faaa1f5c2f1b9ceaf0802c"; // pw: furrow2026
  const ADMIN_HASH      = "78263e182bfcae1e5d2adb340b263603fe7aad47a686b988424940869b2a7a8a"; // pw: gabrison-admin

  const CONTACT_EMAIL = "info@joinfurrow.com"; // where Register / quotation requests are emailed
  const SESSION_KEY   = "furrow_access_v1";

  /* ---- helpers ----------------------------------------------------------- */
  async function sha256(str) {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
  }
  function unlocked() {
    try { return sessionStorage.getItem(SESSION_KEY) === "1"; } catch (e) { return false; }
  }
  function setUnlocked(v) {
    try { v ? sessionStorage.setItem(SESSION_KEY, "1") : sessionStorage.removeItem(SESSION_KEY); } catch (e) {}
  }

  /* ---- styles ------------------------------------------------------------ */
  const CSS = `
  .fg-blur { filter: blur(7px); pointer-events: none; user-select: none; transition: filter .25s ease; }
  /* keep the nav + free ticker sharp; ticker sits above the blur but BELOW the login card.
     IMPORTANT: preserve the nav's own sticky positioning so it doesn't scroll away when locked. */
  body.fg-locked nav { z-index: 4400 !important; filter: none !important; }
  body.fg-locked .ticker-wrap { z-index: 4100 !important; filter: none !important; }
  /* dark wash sits BELOW the ticker so the ticker stays visible; card layer sits ABOVE */
  .fg-backdrop {
    position: fixed; inset: 0; z-index: 3900; display: none;
    background: rgba(11,28,46,.55);
  }
  .fg-backdrop.open { display: block; }
  .fg-overlay {
    position: fixed; inset: 0; z-index: 4200; display: none;
    align-items: flex-start; justify-content: center; padding: 104px 20px 24px;
    background: transparent; pointer-events: none; overflow-y: auto;
  }
  .fg-overlay.open { display: flex; }
  .fg-overlay .fg-card { pointer-events: auto; }
  .fg-card {
    background: #fff; border: 1px solid #E0DAC8; border-radius: 16px;
    width: 100%; max-width: 440px; max-height: calc(100vh - 130px); overflow-y: auto;
    box-shadow: 0 20px 60px rgba(0,0,0,.28); padding: 30px 28px; position: relative; z-index: 4300;
    font-family: Inter, system-ui, sans-serif; color: #0B1C2E;
  }
  .fg-card.wide { max-width: 560px; }
  .fg-wm { font-family: Georgia, 'Times New Roman', serif; font-size: 26px; font-weight: 700; letter-spacing: .02em; color: #0B1C2E; }
  .fg-wm u { text-decoration-color: #C9A84C; }
  .fg-tag { display: inline-block; font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: #C9A84C; margin: 4px 0 18px; }
  .fg-h { font-size: 20px; margin: 0 0 6px; }
  .fg-sub { font-size: 13px; color: #6B6552; line-height: 1.55; margin: 0 0 20px; }
  .fg-label { display:block; font-size: 11px; font-weight: 700; letter-spacing: .03em; margin: 14px 0 6px; text-transform: uppercase; color:#0B1C2E; }
  .fg-input, .fg-textarea, .fg-select {
    width: 100%; padding: 11px 13px; border: 1px solid #E0DAC8; border-radius: 8px;
    font-size: 14px; font-family: inherit; color: #0B1C2E; background:#fff;
  }
  .fg-textarea { min-height: 74px; resize: vertical; }
  .fg-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .fg-btn { width: 100%; margin-top: 20px; background: #0B1C2E; color: #C9A84C; border: none;
    border-radius: 9px; padding: 13px; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; }
  .fg-btn:hover { opacity: .93; }
  .fg-btn.gold { background: #C9A84C; color: #0B1C2E; }
  .fg-alt { text-align: center; font-size: 13px; color: #6B6552; margin-top: 18px; }
  .fg-alt a { color: #0B1C2E; font-weight: 700; cursor: pointer; text-decoration: underline; }
  .fg-msg { font-size: 12.5px; margin-top: 12px; min-height: 16px; text-align: center; }
  .fg-msg.err { color: #8B1A1A; }
  .fg-msg.ok  { color: #1E6B4A; }
  .fg-check { display: flex; align-items: flex-start; gap: 8px; margin-top: 14px; font-size: 12.5px; color:#6B6552; line-height:1.5; }
  .fg-check input { margin-top: 2px; }
  .fg-note { font-size: 11px; color: #9A927E; margin-top: 16px; line-height: 1.5; text-align:center; }
  .fg-logout {
    position: fixed; right: 14px; bottom: 14px; z-index: 3500; display: none;
    background: #0B1C2E; color: #C9A84C; border: 1px solid #C9A84C; border-radius: 999px;
    padding: 8px 15px; font-size: 11px; font-weight: 700; cursor: pointer; font-family: Inter, sans-serif;
    letter-spacing: .04em; box-shadow: 0 4px 14px rgba(0,0,0,.18);
  }
  .fg-logout.show { display: block; }
  @media (max-width: 480px) { .fg-row { grid-template-columns: 1fr; } }
  `;

  /* ---- markup ------------------------------------------------------------ */
  const LOGIN_VIEW = `
    <div class="fg-wm">FU<u>RR</u>OW</div>
    <span class="fg-tag">powered by Gabrison Capital</span>
    <h2 class="fg-h">Subscriber access</h2>
    <p class="fg-sub">Live prices, moving in real time — always free. Go deeper with a FURROW subscription: regional price breakdowns, coffee, cotton and cashew board rates, active tenders, and daily agribusiness intelligence. Sign in to continue.</p>
    <label class="fg-label" for="fgPw">Password</label>
    <input class="fg-input" id="fgPw" type="password" placeholder="Enter subscriber or admin password" autocomplete="off" onkeydown="if(event.key==='Enter')window.__fgLogin()"/>
    <button class="fg-btn" onclick="window.__fgLogin()">Unlock</button>
    <div class="fg-msg" id="fgMsg"></div>
    <p class="fg-alt">No subscription yet? <a onclick="window.__fgView('register')">Register &amp; request access</a></p>
    <p class="fg-note">Live prices stay free, right here at the top of the page — no sign-in needed.</p>
  `;

  const REGISTER_VIEW = `
    <div class="fg-wm">FU<u>RR</u>OW</div>
    <span class="fg-tag">powered by Gabrison Capital</span>
    <h2 class="fg-h">Request a subscription</h2>
    <p class="fg-sub">Tell us about you and your business. We'll follow up with subscription details and pricing. You can also request a quotation for a specific need.</p>

    <label class="fg-label">Full name</label>
    <input class="fg-input" id="fgName" placeholder="Your name"/>
    <div class="fg-row">
      <div><label class="fg-label">Email</label><input class="fg-input" id="fgEmail" type="email" placeholder="you@company.com"/></div>
      <div><label class="fg-label">Phone</label><input class="fg-input" id="fgPhone" placeholder="+255 …"/></div>
    </div>

    <label class="fg-label">Business / organisation</label>
    <input class="fg-input" id="fgCompany" placeholder="Company name"/>
    <div class="fg-row">
      <div><label class="fg-label">Business type</label>
        <select class="fg-select" id="fgType">
          <option value="">Select…</option>
          <option>Farmer / cooperative (AMCOS)</option>
          <option>Trader / aggregator</option>
          <option>Processor / manufacturer</option>
          <option>Exporter / importer</option>
          <option>Financial institution</option>
          <option>Government / NGO</option>
          <option>Other</option>
        </select>
      </div>
      <div><label class="fg-label">Region</label><input class="fg-input" id="fgRegion" placeholder="e.g. Dodoma"/></div>
    </div>

    <label class="fg-label">Request a quotation (optional)</label>
    <textarea class="fg-textarea" id="fgQuote" placeholder="Describe what you'd like a quotation for — e.g. regional price feed, tender alerts, bulk data access, custom reports…"></textarea>

    <label class="fg-check"><input type="checkbox" id="fgQuoteFlag"/> <span>Please include a formal quotation with your reply.</span></label>

    <button class="fg-btn gold" onclick="window.__fgRegister()">Submit request</button>
    <div class="fg-msg" id="fgMsg2"></div>
    <p class="fg-alt">Already a subscriber? <a onclick="window.__fgView('login')">Back to login</a></p>
    <p class="fg-note">We'll review your request and follow up with subscription details and pricing. A team member is usually in touch within one business day.</p>
  `;

  /* ---- build DOM --------------------------------------------------------- */
  function el(tag, attrs, html) {
    const e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(k => e.setAttribute(k, attrs[k]));
    if (html != null) e.innerHTML = html;
    return e;
  }

  let overlay, card, logoutBtn, backdrop;

  function buildGate() {
    document.head.appendChild(el("style", null, CSS));

    backdrop = el("div", { class: "fg-backdrop", id: "fgBackdrop" });
    document.body.appendChild(backdrop);

    overlay = el("div", { class: "fg-overlay", id: "fgOverlay" });
    card = el("div", { class: "fg-card" });
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    logoutBtn = el("button", { class: "fg-logout", id: "fgLogout" }, "Log out");
    logoutBtn.onclick = logout;
    document.body.appendChild(logoutBtn);

    view("login");
  }

  function view(which) {
    card.className = "fg-card";
    card.innerHTML = which === "register" ? REGISTER_VIEW : LOGIN_VIEW;
    setTimeout(function () { const f = document.getElementById(which === "register" ? "fgName" : "fgPw"); if (f) f.focus(); }, 40);
  }

  /* ---- blur / unblur : everything except nav + ticker -------------------- */
  const KEEP_FREE = ["nav", ".ticker-wrap", "#fgOverlay", "#fgBackdrop", "#fgLogout"];
  function isFree(node) {
    return KEEP_FREE.some(sel => (node.matches && node.matches(sel)) || (node.closest && node.closest(sel)));
  }
  function gatedNodes() {
    return Array.prototype.filter.call(document.body.children, function (c) {
      return !isFree(c) && c.tagName !== "SCRIPT" && c.tagName !== "STYLE";
    });
  }
  function blur(on) {
    gatedNodes().forEach(function (n) { n.classList.toggle("fg-blur", on); });
  }

  /* ---- actions ----------------------------------------------------------- */
  async function login() {
    const inp = document.getElementById("fgPw");
    const msg = document.getElementById("fgMsg");
    const h = await sha256("furrow::" + (inp.value || ""));
    if (h === SUBSCRIBER_HASH || h === ADMIN_HASH) {
      grantAccess();
    } else {
      msg.className = "fg-msg err";
      msg.textContent = "That password wasn't recognised. Try again or request access.";
      inp.select();
    }
  }

  function grantAccess() {
    setUnlocked(true);
    document.body.classList.remove("fg-locked");
    backdrop.classList.remove("open");
    overlay.classList.remove("open");
    blur(false);
    logoutBtn.classList.add("show");
    document.body.style.overflow = "";
  }

  function logout() {
    setUnlocked(false);
    logoutBtn.classList.remove("show");
    gate(); // re-lock
  }

  function register() {
    const g = id => (document.getElementById(id) || {}).value || "";
    const name = g("fgName").trim(), email = g("fgEmail").trim();
    const msg = document.getElementById("fgMsg2");
    if (!name || !email) {
      msg.className = "fg-msg err";
      msg.textContent = "Please give at least your name and email.";
      return;
    }
    const wantQuote = (document.getElementById("fgQuoteFlag") || {}).checked;
    const lines = [
      "New FURROW subscription request",
      "--------------------------------",
      "Name:      " + name,
      "Email:     " + email,
      "Phone:     " + g("fgPhone"),
      "Business:  " + g("fgCompany"),
      "Type:      " + g("fgType"),
      "Region:    " + g("fgRegion"),
      "",
      "Quotation requested: " + (wantQuote ? "YES" : "no"),
      "Quotation details:",
      g("fgQuote") || "(none)",
      "",
      "— sent from joinfurrow.com access page"
    ];
    const subject = "FURROW subscription request — " + name + (g("fgCompany") ? " (" + g("fgCompany") + ")" : "");
    const href = "mailto:" + CONTACT_EMAIL +
      "?subject=" + encodeURIComponent(subject) +
      "&body=" + encodeURIComponent(lines.join("\n"));
    window.location.href = href;
    msg.className = "fg-msg ok";
    msg.textContent = "Thank you — your request is on its way. Please send the email that just opened, and we'll be in touch shortly.";
  }

  /* ---- gate on load ------------------------------------------------------ */
  function gate() {
    if (unlocked()) { blur(false); logoutBtn && logoutBtn.classList.add("show"); return; }
    blur(true);
    document.body.classList.add("fg-locked");
    backdrop.classList.add("open");
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  /* ---- expose the few handlers the inline onclicks call ------------------ */
  window.__fgLogin = login;
  window.__fgRegister = register;
  window.__fgView = view;

  /* ---- init -------------------------------------------------------------- */
  function start() {
    buildGate();
    gate();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
