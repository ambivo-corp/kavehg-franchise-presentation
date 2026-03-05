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
            '<td>' + (p.num_views || 0) + '</td>' +
            '<td>' + (p.total_chat_queries || 0) + ' <span style="color:#9ca3af;font-size:.8em">(' + (p.today_chat_queries || 0) + ')</span></td>' +
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
  // Section toggle helper
  // ══════════════════════════════════════════════════
  function initSectionToggle(checkboxEl, sectionEl) {
    if (!checkboxEl || !sectionEl) return;
    checkboxEl.addEventListener("change", function () {
      sectionEl.style.display = checkboxEl.checked ? "" : "none";
    });
  }
  // Keep old name for compatibility
  function initAccessToggle(c, s) { initSectionToggle(c, s); }

  // ══════════════════════════════════════════════════
  // Logo file preview helper
  // ══════════════════════════════════════════════════
  function initLogoFilePreview(fileInputEl, previewWrapEl, previewImgEl) {
    if (!fileInputEl || !previewWrapEl || !previewImgEl) return;
    fileInputEl.addEventListener("change", function () {
      var file = fileInputEl.files[0];
      if (!file) return;
      if (file.size > 1024 * 1024) { alert("Logo must be under 1 MB."); fileInputEl.value = ""; return; }
      var reader = new FileReader();
      reader.onload = function (e) {
        previewImgEl.src = e.target.result;
        previewWrapEl.style.display = "";
      };
      reader.readAsDataURL(file);
    });
  }

  function getHeaderFields() {
    return {
      enabled: document.getElementById("f_header") ? document.getElementById("f_header").checked : false,
      link_url: (document.getElementById("f_link_url") || {}).value || null,
      link_text: (document.getElementById("f_link_text") || {}).value || null,
      email: (document.getElementById("f_header_email") || {}).value || null,
      phone: (document.getElementById("f_header_phone") || {}).value || null,
      text: (document.getElementById("f_header_text") || {}).value || null,
    };
  }

  function uploadLogo(presentationId, fileInput) {
    if (!fileInput || !fileInput.files || !fileInput.files[0]) return Promise.resolve(null);
    var formData = new FormData();
    formData.append("file", fileInput.files[0]);
    return fetch(API + "/api/presentations/" + presentationId + "/logo", {
      method: "POST",
      headers: { "Authorization": "Bearer " + token },
      body: formData,
    }).then(handleAuth).then(function (r) { return r.json(); });
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
    initSectionToggle(document.getElementById("f_header"), document.getElementById("headerSection"));
    initLogoFilePreview(document.getElementById("f_logo"), document.getElementById("logoPreviewWrap"), document.getElementById("logoPreview"));

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
        header: getHeaderFields(),
      };
      if (body.access_protected) {
        body.num_access_codes = parseInt(document.getElementById("f_num_codes").value, 10) || 3;
      }
      var slug = document.getElementById("f_slug").value.trim();
      if (slug) body.slug = slug;

      var logoInput = document.getElementById("f_logo");

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
          // Upload logo if selected
          if (logoInput && logoInput.files && logoInput.files[0]) {
            return uploadLogo(result.id, logoInput).then(function () {
              window.location.href = "/dashboard";
            });
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
    initSectionToggle(document.getElementById("f_header"), document.getElementById("headerSection"));
    initLogoFilePreview(document.getElementById("f_logo"), document.getElementById("logoPreviewWrap"), document.getElementById("logoPreview"));

    var pendingLogoDelete = false;

    var accessCodes = [];
    var CODE_RE = /^[A-Z0-9]{3,12}$/;

    function renderAccessCodes() {
      var list = document.getElementById("accessCodesList");
      if (!list) return;
      if (!accessCodes.length) {
        list.innerHTML = '<p style="color:#9ca3af;font-size:.85rem">No codes yet. Add one or auto-generate.</p>';
        return;
      }
      list.innerHTML = accessCodes.map(function (c, i) {
        return '<span class="access-code-chip">' + esc(c) +
          ' <span class="code-action" data-edit="' + i + '" title="Edit" style="cursor:pointer;margin-left:.3rem">&#9998;</span>' +
          ' <span class="code-action" data-remove="' + i + '" title="Remove" style="cursor:pointer;color:#ef4444">&times;</span>' +
          '</span>';
      }).join("");
    }

    function setAccessCodes(codes) {
      accessCodes = (codes || []).slice();
      renderAccessCodes();
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
        setAccessCodes(p.access_codes);

        // Header
        var h = p.header || {};
        var headerCheckbox = document.getElementById("f_header");
        if (headerCheckbox) {
          headerCheckbox.checked = !!h.enabled;
          if (h.enabled) document.getElementById("headerSection").style.display = "";
        }
        if (h.link_url) document.getElementById("f_link_url").value = h.link_url;
        if (h.link_text) document.getElementById("f_link_text").value = h.link_text;
        if (h.email) document.getElementById("f_header_email").value = h.email;
        if (h.phone) document.getElementById("f_header_phone").value = h.phone;
        if (h.text) document.getElementById("f_header_text").value = h.text;
        if (h.logo_url) {
          document.getElementById("logoPreview").src = h.logo_url;
          document.getElementById("logoPreviewWrap").style.display = "";
        }

        // Stats bar
        var statsBar = document.getElementById("statsBar");
        if (statsBar) {
          document.getElementById("statViews").textContent = p.num_views || 0;
          document.getElementById("statQueries").textContent = p.total_chat_queries || 0;
          document.getElementById("statToday").textContent = p.today_chat_queries || 0;
          statsBar.style.display = "";
        }

        document.getElementById("editLoading").style.display = "none";
        document.getElementById("editContent").style.display = "";
      })
      .catch(function (err) {
        document.getElementById("editLoading").textContent = "Error: " + err.message;
      });

    // Code list event delegation (edit / remove)
    var codesList = document.getElementById("accessCodesList");
    if (codesList) {
      codesList.addEventListener("click", function (e) {
        var editIdx = e.target.dataset.edit;
        var removeIdx = e.target.dataset.remove;
        if (editIdx !== undefined) {
          var idx = parseInt(editIdx, 10);
          var newVal = prompt("Edit access code:", accessCodes[idx]);
          if (newVal === null) return;
          newVal = newVal.trim().toUpperCase();
          if (!CODE_RE.test(newVal)) { alert("Invalid code: 3-12 characters, A-Z and 0-9 only."); return; }
          if (accessCodes.indexOf(newVal) !== -1 && accessCodes[idx] !== newVal) { alert("Duplicate code."); return; }
          accessCodes[idx] = newVal;
          renderAccessCodes();
        }
        if (removeIdx !== undefined) {
          accessCodes.splice(parseInt(removeIdx, 10), 1);
          renderAccessCodes();
        }
      });
    }

    // Add custom code
    var btnAddCode = document.getElementById("btnAddCode");
    var newCodeInput = document.getElementById("newCodeInput");
    if (btnAddCode && newCodeInput) {
      btnAddCode.addEventListener("click", function () {
        var val = newCodeInput.value.trim().toUpperCase();
        if (!val) return;
        if (!CODE_RE.test(val)) { alert("Invalid code: 3-12 characters, A-Z and 0-9 only."); return; }
        if (accessCodes.indexOf(val) !== -1) { alert("Code already exists."); return; }
        accessCodes.push(val);
        renderAccessCodes();
        newCodeInput.value = "";
      });
      newCodeInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); btnAddCode.click(); }
      });
    }

    // Auto-generate one code
    var btnAutoGen = document.getElementById("btnAutoGen");
    if (btnAutoGen) {
      btnAutoGen.addEventListener("click", function () {
        var chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        var code;
        do {
          code = "";
          for (var i = 0; i < 6; i++) code += chars.charAt(Math.floor(Math.random() * chars.length));
        } while (accessCodes.indexOf(code) !== -1);
        accessCodes.push(code);
        renderAccessCodes();
      });
    }

    // Regenerate all codes (immediate server call)
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
            setAccessCodes(p.access_codes);
            regenBtn.disabled = false;
            regenBtn.textContent = "Regenerate All";
          })
          .catch(function () {
            regenBtn.disabled = false;
            regenBtn.textContent = "Regenerate All";
          });
      });
    }

    // Remove logo button
    var btnRemoveLogo = document.getElementById("btnRemoveLogo");
    if (btnRemoveLogo) {
      btnRemoveLogo.addEventListener("click", function () {
        pendingLogoDelete = true;
        document.getElementById("logoPreview").src = "";
        document.getElementById("logoPreviewWrap").style.display = "none";
        document.getElementById("f_logo").value = "";
      });
    }

    // ── Chat Queries Modal ──
    var queriesModal = document.getElementById("queriesModal");
    var queriesCurrentPage = 1;
    var queriesPageSize = 25;

    function loadQueries(page) {
      queriesCurrentPage = page;
      var body = document.getElementById("queriesBody");
      body.innerHTML = '<div class="loading">Loading...</div>';

      fetch(API + "/api/presentations/" + editId + "/queries?page=" + page + "&page_size=" + queriesPageSize, {
        headers: authHeaders(),
      })
        .then(handleAuth)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data.items || !data.items.length) {
            body.innerHTML = '<p style="color:#9ca3af;text-align:center;padding:2rem 0">No queries recorded yet.</p>';
            document.getElementById("queriesFooter").style.display = "none";
            return;
          }
          var html = '<table class="query-table"><thead><tr>' +
            '<th>Question</th><th>Date / Time</th><th>IP</th><th>Code</th><th></th>' +
            '</tr></thead><tbody>';
          data.items.forEach(function (q) {
            var ts = q.created_at ? new Date(q.created_at).toLocaleString() : q.date;
            html += '<tr>' +
              '<td class="q-text" title="' + esc(q.question) + '">' + esc(q.question) + '</td>' +
              '<td class="q-meta">' + esc(ts) + '</td>' +
              '<td class="q-meta">' + esc(q.client_ip) + '</td>' +
              '<td class="q-meta">' + esc(q.access_code || '—') + '</td>' +
              '<td><button class="btn-danger-sm" data-del-query="' + q.id + '" title="Delete">&times;</button></td>' +
              '</tr>';
          });
          html += '</tbody></table>';
          body.innerHTML = html;

          // Pagination
          var totalPages = Math.ceil(data.total / data.page_size);
          var footer = document.getElementById("queriesFooter");
          footer.style.display = totalPages > 1 ? "" : "none";
          document.getElementById("queriesPageInfo").textContent = "Page " + data.page + " of " + totalPages;
          document.getElementById("btnQueriesPrev").disabled = data.page <= 1;
          document.getElementById("btnQueriesNext").disabled = data.page >= totalPages;
        })
        .catch(function (err) {
          body.innerHTML = '<p style="color:#b91c1c;text-align:center">Error: ' + esc(err.message) + '</p>';
        });
    }

    // Open modal on stat click
    var statQueriesWrap = document.getElementById("statQueriesWrap");
    if (statQueriesWrap && queriesModal) {
      statQueriesWrap.addEventListener("click", function () {
        queriesModal.style.display = "";
        loadQueries(1);
      });
    }

    // Close modal
    var btnCloseQueries = document.getElementById("btnCloseQueries");
    if (btnCloseQueries) {
      btnCloseQueries.addEventListener("click", function () { queriesModal.style.display = "none"; });
    }
    if (queriesModal) {
      queriesModal.addEventListener("click", function (e) {
        if (e.target === queriesModal) queriesModal.style.display = "none";
      });
    }

    // Pagination buttons
    var btnPrev = document.getElementById("btnQueriesPrev");
    var btnNext = document.getElementById("btnQueriesNext");
    if (btnPrev) btnPrev.addEventListener("click", function () { loadQueries(queriesCurrentPage - 1); });
    if (btnNext) btnNext.addEventListener("click", function () { loadQueries(queriesCurrentPage + 1); });

    // Delete single query (delegation)
    var queriesBody = document.getElementById("queriesBody");
    if (queriesBody) {
      queriesBody.addEventListener("click", function (e) {
        var qid = e.target.dataset.delQuery;
        if (!qid) return;
        fetch(API + "/api/presentations/" + editId + "/queries/" + qid, {
          method: "DELETE", headers: authHeaders(),
        })
          .then(handleAuth)
          .then(function () { loadQueries(queriesCurrentPage); });
      });
    }

    // Clear all queries
    var btnClearAll = document.getElementById("btnClearAllQueries");
    if (btnClearAll) {
      btnClearAll.addEventListener("click", function () {
        if (!confirm("Delete ALL chat queries for this presentation? This cannot be undone.")) return;
        fetch(API + "/api/presentations/" + editId + "/queries", {
          method: "DELETE", headers: authHeaders(),
        })
          .then(handleAuth)
          .then(function () {
            loadQueries(1);
            document.getElementById("statQueries").textContent = "0";
            document.getElementById("statToday").textContent = "0";
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

      var isProtected = document.getElementById("f_access").checked;
      var body = {
        title: document.getElementById("f_title").value.trim(),
        markdown_content: document.getElementById("f_md").value,
        description: document.getElementById("f_desc").value.trim() || null,
        tags: tagsWidgetEdit.getTags(),
        chat_enabled: document.getElementById("f_chat").checked,
        access_protected: isProtected,
        header: getHeaderFields(),
      };
      if (isProtected) {
        body.access_codes = accessCodes;
      } else {
        body.access_codes = [];
      }

      var logoInput = document.getElementById("f_logo");

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
          // Handle logo upload or delete
          if (pendingLogoDelete) {
            return fetch(API + "/api/presentations/" + editId + "/logo", {
              method: "DELETE",
              headers: authHeaders(),
            }).then(handleAuth);
          }
          if (logoInput && logoInput.files && logoInput.files[0]) {
            return uploadLogo(editId, logoInput);
          }
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
