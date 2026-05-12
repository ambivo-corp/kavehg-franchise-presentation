/* Chapters editor — list, bulk upload, drag-drop reorder, inline edit.
 *
 * Lives alongside dashboard.js on the edit page. Only shows the
 * Chapters section when the presentation is a multi-chapter book.
 */
(function () {
  "use strict";

  const script = document.currentScript;
  if (!script) return;
  const presentationId = script.getAttribute("data-presentation-id");
  if (!presentationId) return;

  const section = document.getElementById("chaptersSection");
  const list = document.getElementById("chaptersList");
  const countEl = document.getElementById("chaptersCount");
  const fileInput = document.getElementById("chaptersFileInput");
  const pickBtn = document.getElementById("btnChaptersPick");
  const uploadZone = document.getElementById("chaptersUploadZone");
  const uploadStatus = document.getElementById("chaptersUploadStatus");

  // Modal references (slice 8d)
  const modal = document.getElementById("chapterModal");
  const modalTitle = document.getElementById("chapterModalTitle");
  const modalClose = document.getElementById("btnChapterClose");
  const modalCancel = document.getElementById("btnChapterCancel");
  const modalSave = document.getElementById("btnChapterSave");
  const inputTitle = document.getElementById("chapterTitleInput");
  const inputSection = document.getElementById("chapterSectionInput");
  const inputMarkdown = document.getElementById("chapterMarkdownInput");
  const modalErr = document.getElementById("chapterFormError");

  if (!section || !list) return;

  let chapters = [];
  let editingChapter = null;

  function authHeaders() {
    const h = { "Content-Type": "application/json" };
    try {
      const t = localStorage.getItem("cp_token");
      if (t) h["Authorization"] = "Bearer " + t;
    } catch (_) {}
    return h;
  }

  function escapeHtml(s) {
    return (s == null ? "" : String(s))
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function apiFetch(path, init) {
    init = init || {};
    init.headers = Object.assign({}, authHeaders(), init.headers || {});
    const resp = await fetch(path, init);
    if (!resp.ok) {
      let detail = "HTTP " + resp.status;
      try {
        const body = await resp.json();
        if (body && body.detail) detail = body.detail;
      } catch (_) {}
      throw new Error(detail);
    }
    if (resp.status === 204) return null;
    return resp.json();
  }

  function renderList() {
    if (!chapters.length) {
      list.innerHTML =
        '<li class="chapters-empty">No chapters yet. Upload .md / .pdf / .docx / .pptx files above to create a multi-chapter book.</li>';
      if (countEl) countEl.textContent = "";
      return;
    }
    if (countEl) {
      countEl.textContent =
        chapters.length + " chapter" + (chapters.length === 1 ? "" : "s");
    }

    const rows = chapters
      .slice()
      .sort(function (a, b) {
        return (a.order || 0) - (b.order || 0);
      })
      .map(function (ch, idx) {
        const indexed = ch.indexed_at ? "indexed" : "pending reindex";
        const section = ch.section
          ? '<span class="chapter-section">' + escapeHtml(ch.section) + "</span>"
          : "";
        return (
          '<li class="chapter-row" draggable="true" data-id="' +
          escapeHtml(ch.chapter_id) +
          '">' +
          '<span class="chapter-drag" title="Drag to reorder">⋮⋮</span>' +
          '<span class="chapter-order">' +
          (idx + 1) +
          "</span>" +
          '<div class="chapter-main">' +
          '<a href="#" class="chapter-title" data-action="edit" data-id="' +
          escapeHtml(ch.chapter_id) +
          '">' +
          escapeHtml(ch.title) +
          "</a>" +
          section +
          '<span class="chapter-slug">/' +
          escapeHtml(ch.slug) +
          "</span>" +
          "</div>" +
          '<span class="chapter-indexed" title="KB index status">' +
          indexed +
          "</span>" +
          '<button type="button" class="btn-sm btn-ghost chapter-del" ' +
          'data-action="delete" data-id="' +
          escapeHtml(ch.chapter_id) +
          '">Delete</button>' +
          "</li>"
        );
      })
      .join("");
    list.innerHTML = rows;
  }

  async function loadChapters() {
    try {
      const resp = await apiFetch(
        "/api/presentations/" + presentationId + "/chapters",
        { method: "GET" }
      );
      chapters = Array.isArray(resp) ? resp : [];
      renderList();
    } catch (err) {
      list.innerHTML =
        '<li class="chapters-empty">Failed to load chapters: ' +
        escapeHtml(err.message) +
        "</li>";
    }
  }

  // Public init — called by dashboard.js after the presentation loads.
  // Always shows the chapters section so authors can convert any
  // presentation into a multi-chapter book by uploading files.
  window.initChaptersEditor = function (_presentation) {
    section.style.display = "block";
    loadChapters();
  };

  // ----- Delete -----
  list.addEventListener("click", async function (e) {
    const target = e.target.closest("[data-action]");
    if (!target) return;
    const action = target.getAttribute("data-action");
    const id = target.getAttribute("data-id");
    if (!id) return;

    if (action === "delete") {
      e.preventDefault();
      if (!confirm("Delete this chapter? This cannot be undone.")) return;
      try {
        await apiFetch(
          "/api/presentations/" + presentationId + "/chapters/" + id,
          { method: "DELETE" }
        );
        await loadChapters();
      } catch (err) {
        alert("Delete failed: " + err.message);
      }
      return;
    }

    if (action === "edit") {
      e.preventDefault();
      openChapterModal(id);
    }
  });

  // ----- Bulk upload (slice 8b) -----
  function setUploadStatus(text, kind) {
    if (!uploadStatus) return;
    if (!text) {
      uploadStatus.style.display = "none";
      uploadStatus.textContent = "";
      return;
    }
    uploadStatus.style.display = "block";
    uploadStatus.className =
      "chapters-upload-status status-" + (kind || "info");
    uploadStatus.textContent = text;
  }

  async function uploadFiles(files) {
    if (!files || !files.length) return;
    const fd = new FormData();
    for (let i = 0; i < files.length; i += 1) fd.append("files", files[i]);

    setUploadStatus("Uploading " + files.length + " file(s)…", "info");
    try {
      const headers = authHeaders();
      delete headers["Content-Type"]; // browser sets boundary
      const resp = await fetch(
        "/api/presentations/" +
          presentationId +
          "/chapters/bulk-import",
        { method: "POST", headers: headers, body: fd }
      );
      if (!resp.ok) {
        let detail = "HTTP " + resp.status;
        try {
          const body = await resp.json();
          if (body && body.detail) detail = body.detail;
        } catch (_) {}
        throw new Error(detail);
      }
      const result = await resp.json();
      const c = (result.created || []).length;
      const u = (result.updated || []).length;
      const f = (result.failed || []).length;
      let msg = "Created " + c + ", updated " + u;
      if (f) {
        msg +=
          ", " +
          f +
          " failed: " +
          (result.failed || [])
            .map(function (x) {
              return x.filename + " — " + x.error;
            })
            .join("; ");
      }
      setUploadStatus(msg, f ? "warn" : "ok");
      await loadChapters();
      // Show chapters section if it wasn't visible (first import)
      section.style.display = "block";
    } catch (err) {
      setUploadStatus("Upload failed: " + err.message, "error");
    }
  }

  if (pickBtn) {
    pickBtn.addEventListener("click", function () {
      if (fileInput) fileInput.click();
    });
  }
  if (fileInput) {
    fileInput.addEventListener("change", function () {
      uploadFiles(fileInput.files);
      fileInput.value = "";
    });
  }
  if (uploadZone) {
    ["dragenter", "dragover"].forEach(function (evt) {
      uploadZone.addEventListener(evt, function (e) {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (evt) {
      uploadZone.addEventListener(evt, function (e) {
        e.preventDefault();
        e.stopPropagation();
        uploadZone.classList.remove("is-dragover");
      });
    });
    uploadZone.addEventListener("drop", function (e) {
      if (e.dataTransfer && e.dataTransfer.files) {
        uploadFiles(e.dataTransfer.files);
      }
    });
  }

  // ----- Drag-drop reorder (slice 8c) -----
  let dragId = null;

  list.addEventListener("dragstart", function (e) {
    const row = e.target.closest(".chapter-row");
    if (!row) return;
    dragId = row.getAttribute("data-id");
    row.classList.add("is-dragging");
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", dragId); } catch (_) {}
    }
  });

  list.addEventListener("dragend", function (e) {
    const row = e.target.closest(".chapter-row");
    if (row) row.classList.remove("is-dragging");
    dragId = null;
    list
      .querySelectorAll(".chapter-row.is-dragover")
      .forEach(function (r) { r.classList.remove("is-dragover"); });
  });

  list.addEventListener("dragover", function (e) {
    e.preventDefault();
    const row = e.target.closest(".chapter-row");
    if (!row || row.getAttribute("data-id") === dragId) return;
    list
      .querySelectorAll(".chapter-row.is-dragover")
      .forEach(function (r) { r.classList.remove("is-dragover"); });
    row.classList.add("is-dragover");
  });

  list.addEventListener("drop", async function (e) {
    e.preventDefault();
    const row = e.target.closest(".chapter-row");
    if (!row || !dragId) return;
    const targetId = row.getAttribute("data-id");
    if (!targetId || targetId === dragId) return;

    // Build new order: move dragId before targetId
    const ids = Array.from(list.querySelectorAll(".chapter-row")).map(
      function (r) { return r.getAttribute("data-id"); }
    );
    const fromIdx = ids.indexOf(dragId);
    const toIdx = ids.indexOf(targetId);
    if (fromIdx < 0 || toIdx < 0) return;
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, dragId);

    try {
      const updated = await apiFetch(
        "/api/presentations/" + presentationId + "/chapters/reorder",
        { method: "PUT", body: JSON.stringify({ chapter_ids: ids }) }
      );
      chapters = updated;
      renderList();
    } catch (err) {
      alert("Reorder failed: " + err.message);
      await loadChapters();
    }
  });

  // ----- Inline editor (slice 8d) -----
  function openChapterModal(id) {
    if (!modal) return;
    apiFetch("/api/presentations/" + presentationId + "/chapters/" + id, {
      method: "GET",
    })
      .then(function (ch) {
        editingChapter = ch;
        if (modalTitle) modalTitle.textContent = "Edit: " + ch.title;
        if (inputTitle) inputTitle.value = ch.title || "";
        if (inputSection) inputSection.value = ch.section || "";
        if (inputMarkdown) inputMarkdown.value = ch.markdown_content || "";
        if (modalErr) {
          modalErr.style.display = "none";
          modalErr.textContent = "";
        }
        modal.style.display = "flex";
      })
      .catch(function (err) {
        alert("Could not open chapter: " + err.message);
      });
  }

  function closeChapterModal() {
    if (modal) modal.style.display = "none";
    editingChapter = null;
  }

  if (modalClose) modalClose.addEventListener("click", closeChapterModal);
  if (modalCancel) modalCancel.addEventListener("click", closeChapterModal);

  if (modalSave) {
    modalSave.addEventListener("click", async function () {
      if (!editingChapter) return;
      const payload = {
        title: (inputTitle && inputTitle.value || "").trim(),
        section: inputSection && inputSection.value || null,
        markdown_content: inputMarkdown ? inputMarkdown.value : "",
        content_type: "markdown",
      };
      if (!payload.title) {
        if (modalErr) {
          modalErr.style.display = "block";
          modalErr.textContent = "Title is required";
        }
        return;
      }
      try {
        await apiFetch(
          "/api/presentations/" +
            presentationId +
            "/chapters/" +
            editingChapter.chapter_id,
          { method: "PUT", body: JSON.stringify(payload) }
        );
        closeChapterModal();
        await loadChapters();
      } catch (err) {
        if (modalErr) {
          modalErr.style.display = "block";
          modalErr.textContent = err.message;
        }
      }
    });
  }
})();
