/**
 * Shared dashboard logic — auth guard, list, create, edit, tags, preview
 */
(function () {
  "use strict";

  // ── Auth guard ──
  var token = localStorage.getItem("cp_token");
  var user = JSON.parse(localStorage.getItem("cp_user") || "null");
  if (!token || !user) { window.location.href = "/login"; return; }

  // Populate nav user name
  var userNameEl = document.getElementById("userName");
  if (userNameEl) userNameEl.textContent = user.name || user.email;

  // API base injected via template data attribute
  var API = (document.body.dataset.api || "").replace(/\/$/, "");

  function authHeaders() {
    return { "Authorization": "Bearer " + token, "Content-Type": "application/json" };
  }

  function handleAuth(r) {
    if (r.status === 401) { logout(); throw new Error("Session expired"); }
    return r;
  }

  function esc(s) {
    var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML;
  }

  // ── Logout ──
  window.logout = function () {
    localStorage.removeItem("cp_token");
    localStorage.removeItem("cp_user");
    window.location.href = "/login";
  };

  // ══════════════════════════════════════════════════
  // Dashboard list page
  // ══════════════════════════════════════════════════
  var tbody = document.getElementById("tbody");
  if (tbody) {
    loadList();
  }

  function loadList() {
    var loadingEl = document.getElementById("loading");
    var tableEl = document.getElementById("table");
    var emptyEl = document.getElementById("empty");
    loadingEl.style.display = "";
    tableEl.style.display = "none";
    emptyEl.style.display = "none";

    fetch(API + "/api/presentations", { headers: authHeaders() })
      .then(handleAuth)
      .then(function (r) { return r.json(); })
      .then(function (list) {
        loadingEl.style.display = "none";
        if (!list.length) { emptyEl.style.display = ""; return; }
        tableEl.style.display = "";
        tbody.innerHTML = "";
        list.forEach(function (p) {
          var tr = document.createElement("tr");
          var protectedBadge = p.access_protected
            ? ' <span class="badge badge-amber">Protected</span>'
            : '';
          tr.innerHTML =
            '<td>' + esc(p.title) + protectedBadge + '</td>' +
            '<td><a class="link" href="/p/' + esc(p.slug) + '" target="_blank">/p/' + esc(p.slug) + '</a></td>' +
            '<td><span class="badge ' + (p.is_published ? 'badge-green' : 'badge-gray') + '">' +
              (p.is_published ? 'Published' : 'Draft') + '</span></td>' +
            '<td>' + (p.chat_enabled ? 'On' : 'Off') + '</td>' +
            '<td>' + new Date(p.created_at).toLocaleDateString() + '</td>' +
            '<td style="white-space:nowrap">' +
              '<a class="link" href="/dashboard/edit/' + p.id + '" style="margin-right:.5rem">Edit</a>' +
              '<button class="btn-danger-sm" data-toggle="' + p.id + '">Toggle</button> ' +
              '<button class="btn-danger-sm" data-delete="' + p.id + '">Delete</button>' +
            '</td>';
          tbody.appendChild(tr);
        });

        // Bind toggle / delete via delegation
        tbody.onclick = function (e) {
          var tid = e.target.dataset.toggle;
          var did = e.target.dataset["delete"];
          if (tid) togglePublish(tid);
          if (did) del(did);
        };
      })
      .catch(function (err) {
        loadingEl.textContent = "Error loading: " + err.message;
      });
  }

  function togglePublish(id) {
    fetch(API + "/api/presentations/" + id + "/publish", { method: "PATCH", headers: authHeaders() })
      .then(handleAuth)
      .then(function () { loadList(); });
  }

  function del(id) {
    if (!confirm("Delete this presentation? The knowledge base will also be removed.")) return;
    fetch(API + "/api/presentations/" + id, { method: "DELETE", headers: authHeaders() })
      .then(handleAuth)
      .then(function () { loadList(); });
  }

  // ══════════════════════════════════════════════════
  // Tags input widget
  // ══════════════════════════════════════════════════
  window.initTagsInput = function (containerEl) {
    var tags = [];
    var input = containerEl.querySelector("input");

    function render() {
      // Remove old tag elements
      containerEl.querySelectorAll(".tag").forEach(function (el) { el.remove(); });
      tags.forEach(function (tag, i) {
        var span = document.createElement("span");
        span.className = "tag";
        span.innerHTML = esc(tag) + ' <span class="tag-remove" data-idx="' + i + '">&times;</span>';
        containerEl.insertBefore(span, input);
      });
    }

    function addTag(val) {
      val = val.trim().toLowerCase();
      if (val && tags.indexOf(val) === -1) {
        tags.push(val);
        render();
      }
    }

    input.addEventListener("keydown", function (e) {
      if ((e.key === "Enter" || e.key === ",") && input.value.trim()) {
        e.preventDefault();
        addTag(input.value.replace(/,/g, ""));
        input.value = "";
      }
      if (e.key === "Backspace" && !input.value && tags.length) {
        tags.pop();
        render();
      }
    });

    containerEl.addEventListener("click", function (e) {
      if (e.target.classList.contains("tag-remove")) {
        tags.splice(parseInt(e.target.dataset.idx, 10), 1);
        render();
      }
      input.focus();
    });

    return {
      getTags: function () { return tags.slice(); },
      setTags: function (arr) { tags = (arr || []).slice(); render(); }
    };
  };

  // ══════════════════════════════════════════════════
  // Shared HTML detection + conversion helper
  // ══════════════════════════════════════════════════
  var HTML_RE = /^\s*<!DOCTYPE|^\s*<html|^\s*<head|^\s*<body|<\/(div|p|table|h[1-6]|ul|ol|section|article|body|html)>/i;

  function htmlToMarkdown(html) {
    if (typeof TurndownService === "undefined") return html;

    // Strip non-content elements before conversion
    html = html.replace(/<head[\s\S]*?<\/head>/gi, "");
    html = html.replace(/<style[\s\S]*?<\/style>/gi, "");
    html = html.replace(/<script[\s\S]*?<\/script>/gi, "");
    html = html.replace(/<!--[\s\S]*?-->/g, "");

    // Extract just <body> content if present
    var bodyMatch = html.match(/<body[^>]*>([\s\S]*)<\/body>/i);
    if (bodyMatch) html = bodyMatch[1];

    // Strip remaining structural wrappers
    html = html.replace(/<!DOCTYPE[^>]*>/gi, "");
    html = html.replace(/<\/?html[^>]*>/gi, "");
    html = html.replace(/<\/?body[^>]*>/gi, "");

    var td = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced", bulletListMarker: "-" });
    if (typeof turndownPluginGfm !== "undefined") td.use(turndownPluginGfm.gfm);
    td.addRule("images", {
      filter: "img",
      replacement: function (content, node) {
        var alt = node.getAttribute("alt") || "image";
        var src = node.getAttribute("src") || "";
        return src ? "![" + alt + "](" + src + ")" : "";
      }
    });
    return td.turndown(html).trim();
  }

  // ══════════════════════════════════════════════════
  // Markdown preview toggle
  // ══════════════════════════════════════════════════
  window.initPreview = function (editorEl, previewEl, btnWrite, btnPreview) {
    btnWrite.addEventListener("click", function () {
      btnWrite.classList.add("active");
      btnPreview.classList.remove("active");
      editorEl.style.display = "";
      previewEl.style.display = "none";
    });
    btnPreview.addEventListener("click", function () {
      btnPreview.classList.add("active");
      btnWrite.classList.remove("active");
      editorEl.style.display = "none";
      previewEl.style.display = "block";

      var content = editorEl.value || "";

      // If content looks like raw HTML, convert to markdown first
      if (HTML_RE.test(content)) {
        content = htmlToMarkdown(content);
        editorEl.value = content; // update textarea so submit sends markdown
      }

      if (typeof marked !== "undefined") {
        previewEl.innerHTML = marked.parse(content);
      } else {
        previewEl.textContent = content || "(preview unavailable — marked.js not loaded)";
      }
    });
  };

  // ══════════════════════════════════════════════════
  // HTML-to-Markdown paste handler (Turndown.js)
  // ══════════════════════════════════════════════════
  window.initPasteHandler = function (textareaEl) {
    if (typeof TurndownService === "undefined") return;

    textareaEl.addEventListener("paste", function (e) {
      var clipboardData = e.clipboardData || window.clipboardData;
      if (!clipboardData) return;

      var html = clipboardData.getData("text/html");

      // If no text/html, check if plain text looks like HTML source code
      if (!html) {
        var plain = clipboardData.getData("text/plain") || "";
        if (HTML_RE.test(plain)) {
          html = plain;
        } else {
          return; // truly plain text — let browser handle it
        }
      }

      e.preventDefault();
      var md = htmlToMarkdown(html);

      // Insert at cursor position
      var start = textareaEl.selectionStart;
      var end = textareaEl.selectionEnd;
      var before = textareaEl.value.substring(0, start);
      var after = textareaEl.value.substring(end);
      textareaEl.value = before + md + after;
      textareaEl.selectionStart = textareaEl.selectionEnd = start + md.length;
      textareaEl.dispatchEvent(new Event("input"));
    });
  };

  // ══════════════════════════════════════════════════
  // Access toggle helper
  // ══════════════════════════════════════════════════
  function initAccessToggle(checkboxEl, sectionEl) {
    if (!checkboxEl || !sectionEl) return;
    checkboxEl.addEventListener("change", function () {
      sectionEl.style.display = checkboxEl.checked ? "" : "none";
    });
  }

  // ══════════════════════════════════════════════════
  // Create form
  // ══════════════════════════════════════════════════
  var createForm = document.getElementById("createForm");
  if (createForm) {
    var tagsWidget = window.initTagsInput(document.getElementById("tagsContainer"));
    window.initPreview(
      document.getElementById("f_md"),
      document.getElementById("mdPreview"),
      document.getElementById("btnWrite"),
      document.getElementById("btnPreview")
    );
    window.initPasteHandler(document.getElementById("f_md"));
    initAccessToggle(document.getElementById("f_access"), document.getElementById("accessCodesSection"));

    // Auto-generate slug from title
    var slugManuallyEdited = false;
    var slugEl = document.getElementById("f_slug");
    slugEl.addEventListener("input", function () { slugManuallyEdited = !!slugEl.value.trim(); });
    document.getElementById("f_title").addEventListener("input", function () {
      if (!slugManuallyEdited) {
        slugEl.value = this.value.trim().toLowerCase()
          .replace(/[^\w\s-]/g, "")
          .replace(/[\s_]+/g, "-")
          .replace(/^-+|-+$/g, "");
      }
    });

    createForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var errEl = document.getElementById("formError");
      var btn = document.getElementById("submitBtn");
      errEl.classList.remove("show");
      btn.disabled = true;
      btn.textContent = "Creating\u2026";

      var body = {
        title: document.getElementById("f_title").value.trim(),
        markdown_content: document.getElementById("f_md").value,
        description: document.getElementById("f_desc").value.trim() || null,
        tags: tagsWidget.getTags(),
        chat_enabled: document.getElementById("f_chat").checked,
        access_protected: document.getElementById("f_access").checked,
      };
      if (body.access_protected) {
        body.num_access_codes = parseInt(document.getElementById("f_num_codes").value, 10) || 3;
      }
      var slug = document.getElementById("f_slug").value.trim();
      if (slug) body.slug = slug;

      fetch(API + "/api/presentations", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(body),
      })
        .then(handleAuth)
        .then(function (r) {
          if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || "Create failed"); });
          return r.json();
        })
        .then(function (result) {
          if (result.access_protected && result.access_codes && result.access_codes.length) {
            alert("Access codes generated:\\n\\n" + result.access_codes.join("\\n") + "\\n\\nSave these codes — they are shown on the edit page too.");
          }
          window.location.href = "/dashboard";
        })
        .catch(function (err) {
          errEl.textContent = err.message;
          errEl.classList.add("show");
          btn.disabled = false;
          btn.textContent = "Create Presentation";
        });
    });
  }

  // ══════════════════════════════════════════════════
  // Edit form
  // ══════════════════════════════════════════════════
  var editForm = document.getElementById("editForm");
  if (editForm) {
    var editId = editForm.dataset.id;
    var tagsWidgetEdit = window.initTagsInput(document.getElementById("tagsContainer"));
    window.initPreview(
      document.getElementById("f_md"),
      document.getElementById("mdPreview"),
      document.getElementById("btnWrite"),
      document.getElementById("btnPreview")
    );
    window.initPasteHandler(document.getElementById("f_md"));
    initAccessToggle(document.getElementById("f_access"), document.getElementById("accessCodesSection"));

    function renderAccessCodes(codes) {
      var display = document.getElementById("accessCodesDisplay");
      if (!display) return;
      if (!codes || !codes.length) {
        display.innerHTML = '<p style="color:#9ca3af;font-size:.85rem">No codes generated yet.</p>';
        return;
      }
      display.innerHTML = '<label style="margin-bottom:.3rem">Current access codes:</label>' +
        '<div class="access-codes-list">' +
        codes.map(function (c) { return '<span class="access-code-chip">' + esc(c) + '</span>'; }).join("") +
        '</div>';
    }

    // Load existing data
    fetch(API + "/api/presentations/" + editId, { headers: authHeaders() })
      .then(handleAuth)
      .then(function (r) {
        if (!r.ok) throw new Error("Failed to load presentation");
        return r.json();
      })
      .then(function (p) {
        document.getElementById("f_title").value = p.title || "";
        document.getElementById("f_desc").value = p.description || "";
        document.getElementById("f_slug").value = p.slug || "";
        document.getElementById("f_md").value = p.markdown_content || "";
        document.getElementById("f_chat").checked = p.chat_enabled !== false;
        tagsWidgetEdit.setTags(p.tags || []);

        // Access codes
        var accessCheckbox = document.getElementById("f_access");
        accessCheckbox.checked = !!p.access_protected;
        if (p.access_protected) {
          document.getElementById("accessCodesSection").style.display = "";
        }
        renderAccessCodes(p.access_codes);

        document.getElementById("editLoading").style.display = "none";
        document.getElementById("editContent").style.display = "";
      })
      .catch(function (err) {
        document.getElementById("editLoading").textContent = "Error: " + err.message;
      });

    // Regenerate codes button
    var regenBtn = document.getElementById("btnRegenCodes");
    if (regenBtn) {
      regenBtn.addEventListener("click", function () {
        if (!confirm("Regenerate all access codes? Old codes will stop working.")) return;
        regenBtn.disabled = true;
        regenBtn.textContent = "Regenerating\u2026";

        fetch(API + "/api/presentations/" + editId, {
          method: "PUT",
          headers: authHeaders(),
          body: JSON.stringify({ regenerate_codes: 3 }),
        })
          .then(handleAuth)
          .then(function (r) { return r.json(); })
          .then(function (p) {
            renderAccessCodes(p.access_codes);
            regenBtn.disabled = false;
            regenBtn.textContent = "Regenerate Codes";
          })
          .catch(function () {
            regenBtn.disabled = false;
            regenBtn.textContent = "Regenerate Codes";
          });
      });
    }

    editForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var errEl = document.getElementById("formError");
      var btn = document.getElementById("submitBtn");
      errEl.classList.remove("show");
      btn.disabled = true;
      btn.textContent = "Updating\u2026";

      var body = {
        title: document.getElementById("f_title").value.trim(),
        markdown_content: document.getElementById("f_md").value,
        description: document.getElementById("f_desc").value.trim() || null,
        tags: tagsWidgetEdit.getTags(),
        chat_enabled: document.getElementById("f_chat").checked,
        access_protected: document.getElementById("f_access").checked,
      };

      fetch(API + "/api/presentations/" + editId, {
        method: "PUT",
        headers: authHeaders(),
        body: JSON.stringify(body),
      })
        .then(handleAuth)
        .then(function (r) {
          if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || "Update failed"); });
          return r.json();
        })
        .then(function () {
          window.location.href = "/dashboard";
        })
        .catch(function (err) {
          errEl.textContent = err.message;
          errEl.classList.add("show");
          btn.disabled = false;
          btn.textContent = "Update Presentation";
        });
    });
  }
})();
