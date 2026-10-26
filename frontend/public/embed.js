/* Jenny sur votre site, une ligne */
(function () {
  "use strict";
  try {
    var doc = document;
    var script =
      doc.currentScript ||
      (function () {
        var list = doc.querySelectorAll('script[data-salon][src*="embed.js"]');
        return list.length ? list[list.length - 1] : null;
      })();
    if (!script) return;

    var slug = (script.getAttribute("data-salon") || "").trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(slug)) {
      if (window.console) console.warn("[Jenny] data-salon manquant ou invalide.");
      return;
    }
    // déjà sur la page
    if (doc.querySelector("[data-jenny-widget]")) return;

    var origin;
    try {
      origin = new URL(script.src, location.href).origin;
    } catch {
      return;
    }

    var color = script.getAttribute("data-color") || "";
    if (!/^#[0-9a-fA-F]{6}$/.test(color)) color = "#FF7F6A";
    var side = script.getAttribute("data-position") === "left" ? "left" : "right";
    var theme = script.getAttribute("data-theme");
    if (theme !== "light" && theme !== "dark") theme = "auto";
    var z = parseInt(script.getAttribute("data-z-index") || "", 10);
    if (!(z > 0 && z < 2147483647)) z = 9999;
    var teaserOn = script.getAttribute("data-teaser") !== "off";

    // texte lisible sur la couleur
    function lum(hex) {
      var out = [1, 3, 5].map(function (i) {
        var v = parseInt(hex.slice(i, i + 2), 16) / 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2];
    }
    var l = lum(color);
    var cWhite = 1.05 / (l + 0.05);
    var cDark = (l + 0.05) / (lum("#1A1D26") + 0.05);
    var fg = cWhite >= 4.5 || cWhite >= cDark ? "#FFFFFF" : "#1A1D26";

    var src =
      origin +
      "/widget/" +
      encodeURIComponent(slug) +
      "?embed=1&c=" +
      encodeURIComponent(color) +
      "&t=" +
      theme;

    var css =
      ":host{all:initial}" +
      "*{box-sizing:border-box}" +
      ".jw{--a:" + color + ";--f:" + fg + ";font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}" +
      ".bubble{position:fixed;bottom:20px;" + side + ":20px;width:58px;height:58px;border-radius:50%;border:0;padding:0;margin:0;" +
      "background:var(--a);color:var(--f);cursor:pointer;display:flex;align-items:center;justify-content:center;" +
      "box-shadow:0 8px 28px rgba(15,10,30,.22),0 2px 6px rgba(15,10,30,.12);transition:transform .18s ease,box-shadow .18s ease}" +
      ".bubble:hover{transform:translateY(-2px);box-shadow:0 12px 32px rgba(15,10,30,.26)}" +
      ".bubble:focus-visible{outline:3px solid var(--a);outline-offset:3px}" +
      ".bubble svg{width:26px;height:26px;display:block}" +
      ".bubble .ic-close{display:none}" +
      ".open .bubble .ic-chat{display:none}.open .bubble .ic-close{display:block}" +
      ".badge{position:absolute;top:-3px;" + (side === "left" ? "left" : "right") + ":-3px;min-width:20px;height:20px;padding:0 6px;border-radius:10px;" +
      "background:#E5484D;color:#fff;font-size:12px;font-weight:700;line-height:20px;text-align:center;border:2px solid #fff}" +
      ".badge[hidden]{display:none}" +
      ".panel{position:fixed;bottom:92px;" + side + ":20px;width:380px;max-width:calc(100vw - 40px);height:640px;" +
      "max-height:calc(100vh - 116px);border-radius:20px;overflow:hidden;background:#fff;" +
      "box-shadow:0 24px 64px rgba(15,10,30,.28),0 4px 14px rgba(15,10,30,.12);" +
      "opacity:0;visibility:hidden;transform:translateY(14px) scale(.98);transform-origin:bottom " + side + ";" +
      "transition:opacity .2s ease,transform .2s ease,visibility 0s linear .2s}" +
      ".open .panel{opacity:1;visibility:visible;transform:none;transition:opacity .2s ease,transform .2s ease,visibility 0s}" +
      ".panel iframe{width:100%;height:100%;border:0;display:block;background:transparent}" +
      ".teaser{position:fixed;bottom:90px;" + side + ":20px;max-width:260px;border-radius:16px;" +
      "background:#fff;box-shadow:0 10px 30px rgba(15,10,30,.18);animation:jwIn .25s ease-out}" +
      ".teaser[hidden],.open .teaser{display:none}" +
      ".teaser .say{display:block;width:100%;margin:0;padding:12px 34px 12px 14px;border:0;border-radius:16px;background:transparent;" +
      "color:#1A1D26;font:inherit;font-size:14px;line-height:1.4;text-align:left;cursor:pointer}" +
      ".teaser .x{position:absolute;top:6px;right:6px;width:24px;height:24px;border:0;border-radius:8px;background:transparent;" +
      "color:#626875;font-size:16px;line-height:1;cursor:pointer;padding:0}" +
      ".teaser button:focus-visible{outline:2px solid #1A1D26;outline-offset:2px}" +
      "@keyframes jwIn{from{opacity:0;transform:translateY(6px)}}" +
      "@media (max-width:480px){.panel{top:0;left:0;right:0;bottom:0;width:100%;max-width:none;height:100%;max-height:none;border-radius:0}" +
      ".open .bubble{display:none}}" +
      "@media (prefers-reduced-motion:reduce){.bubble,.panel,.open .panel{transition:none}.teaser{animation:none}.bubble:hover{transform:none}}";

    var svgChat =
      '<svg class="ic-chat" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 20.5l1.5-4.6a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 8.4-8.6 8.4 8.4 0 0 1 9 8z"/></svg>';
    var svgClose =
      '<svg class="ic-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6L6 18"/></svg>';

    var host, root, wrap, bubble, panel, badge, teaser, iframe;
    var isOpen = false;
    var ready = false;
    var savedOverflow = null;
    var teaserKey = "jw-teaser:" + slug;
    var mobile = window.matchMedia ? window.matchMedia("(max-width: 480px)") : null;

    function post(type) {
      if (!iframe || !iframe.contentWindow || !ready) return;
      try {
        iframe.contentWindow.postMessage({ jw: 1, type: type }, origin);
      } catch {
        // ignore
      }
    }

    function ensureFrame() {
      if (iframe) return;
      iframe = doc.createElement("iframe");
      iframe.src = src;
      iframe.title = "Discussion avec Jenny, assistante virtuelle";
      iframe.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
      panel.appendChild(iframe);
    }

    // scroll page bloqué sur mobile
    function lockScroll(on) {
      var el = doc.documentElement;
      if (on && mobile && mobile.matches) {
        if (savedOverflow === null) savedOverflow = el.style.overflow;
        el.style.overflow = "hidden";
      } else if (!on && savedOverflow !== null) {
        el.style.overflow = savedOverflow;
        savedOverflow = null;
      }
    }

    function setBadge(n) {
      if (n > 0) {
        badge.textContent = n > 9 ? "9+" : String(n);
        badge.hidden = false;
        bubble.setAttribute("aria-label", "Ouvrir la discussion avec Jenny, " + n + " nouveau(x) message(s)");
      } else {
        badge.hidden = true;
        bubble.setAttribute(
          "aria-label",
          isOpen ? "Fermer la discussion avec Jenny" : "Ouvrir la discussion avec Jenny, assistante virtuelle"
        );
      }
    }

    function hideTeaser(remember) {
      if (teaser) teaser.hidden = true;
      if (remember) {
        try {
          sessionStorage.setItem(teaserKey, "1");
        } catch {
          // stockage bloqué
        }
      }
    }

    function openPanel() {
      if (isOpen) return;
      ensureFrame();
      isOpen = true;
      wrap.classList.add("open");
      panel.removeAttribute("inert");
      panel.setAttribute("aria-hidden", "false");
      bubble.setAttribute("aria-expanded", "true");
      setBadge(0);
      hideTeaser(true);
      lockScroll(true);
      try {
        iframe.focus();
      } catch {
        // ignore
      }
      post("open");
    }

    function closePanel(giveFocus) {
      if (!isOpen) return;
      isOpen = false;
      wrap.classList.remove("open");
      panel.setAttribute("inert", "");
      panel.setAttribute("aria-hidden", "true");
      bubble.setAttribute("aria-expanded", "false");
      setBadge(0);
      lockScroll(false);
      post("closed");
      if (giveFocus) bubble.focus();
    }

    function onMessage(e) {
      if (!iframe || e.source !== iframe.contentWindow || e.origin !== origin) return;
      var d = e.data;
      if (!d || d.jw !== 1) return;
      if (d.type === "ready") {
        ready = true;
        if (isOpen) {
          try {
            iframe.focus();
          } catch {
            // ignore
          }
          post("open");
        }
      } else if (d.type === "close") {
        closePanel(true);
      } else if (d.type === "unread" && !isOpen) {
        var n = parseInt(d.count, 10);
        setBadge(n > 0 ? n : 0);
      }
    }

    function mount() {
      if (doc.querySelector("[data-jenny-widget]")) return;
      host = doc.createElement("div");
      // sans shadow dom, on s'abstient
      if (!host.attachShadow) return;
      host.setAttribute("data-jenny-widget", "");
      host.style.cssText =
        "all:initial;position:fixed;bottom:0;" + side + ":0;width:0;height:0;z-index:" + z + ";";
      root = host.attachShadow({ mode: "open" });

      var style = doc.createElement("style");
      style.textContent = css;
      wrap = doc.createElement("div");
      wrap.className = "jw";

      panel = doc.createElement("div");
      panel.className = "panel";
      panel.id = "jw-panel";
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-label", "Discussion avec Jenny, assistante virtuelle");
      panel.setAttribute("aria-hidden", "true");
      panel.setAttribute("inert", "");

      bubble = doc.createElement("button");
      bubble.type = "button";
      bubble.className = "bubble";
      bubble.setAttribute("aria-expanded", "false");
      bubble.setAttribute("aria-controls", "jw-panel");
      bubble.innerHTML = svgChat + svgClose;
      badge = doc.createElement("span");
      badge.className = "badge";
      badge.hidden = true;
      badge.setAttribute("aria-hidden", "true");
      bubble.appendChild(badge);
      setBadge(0);

      bubble.addEventListener("click", function () {
        if (isOpen) closePanel(true);
        else openPanel();
      });
      // préchargement à l'approche
      bubble.addEventListener("pointerenter", ensureFrame, { once: true });
      bubble.addEventListener("focus", ensureFrame, { once: true });

      wrap.appendChild(panel);
      wrap.appendChild(bubble);

      if (teaserOn) {
        var seen = false;
        try {
          seen = sessionStorage.getItem(teaserKey) === "1";
        } catch {
          seen = false;
        }
        if (!seen) {
          teaser = doc.createElement("div");
          teaser.className = "teaser";
          teaser.hidden = true;
          var say = doc.createElement("button");
          say.type = "button";
          say.className = "say";
          say.textContent = "Une question ? Je suis Jenny, l'assistante virtuelle du salon.";
          say.addEventListener("click", openPanel);
          var x = doc.createElement("button");
          x.type = "button";
          x.className = "x";
          x.setAttribute("aria-label", "Masquer le message");
          x.textContent = "×";
          x.addEventListener("click", function () {
            hideTeaser(true);
          });
          teaser.appendChild(say);
          teaser.appendChild(x);
          wrap.appendChild(teaser);
          setTimeout(function () {
            if (!isOpen && teaser) teaser.hidden = false;
          }, 6000);
        }
      }

      root.appendChild(style);
      root.appendChild(wrap);
      doc.body.appendChild(host);

      window.addEventListener("message", onMessage);
      doc.addEventListener("keydown", function (e) {
        if (isOpen && (e.key === "Escape" || e.key === "Esc")) closePanel(true);
      });
      // api sans globale
      doc.addEventListener("jenny:open", openPanel);
      doc.addEventListener("jenny:close", function () {
        closePanel(false);
      });
      doc.addEventListener("click", function (e) {
        var t = e.target;
        var el = t && t.closest ? t.closest("[data-jenny-open]") : null;
        if (el) {
          e.preventDefault();
          openPanel();
        }
      });
    }

    if (doc.body) mount();
    else doc.addEventListener("DOMContentLoaded", mount);
  } catch (err) {
    if (window.console) console.warn("[Jenny] widget non chargé :", err);
  }
})();
