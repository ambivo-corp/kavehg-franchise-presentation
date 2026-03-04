(function () {
  "use strict";

  var script = document.currentScript;
  var presentationId = script.getAttribute("data-presentation-id");
  var chatEnabled = script.getAttribute("data-chat-enabled") === "true";
  var apiBase = script.getAttribute("data-api-base") || "";

  if (!chatEnabled || !presentationId) return;

  var SESSION_KEY = "cp_session_" + presentationId;
  var sessionId = localStorage.getItem(SESSION_KEY) || null;
  var isStreaming = false;

  // ── Build DOM ──
  var bubble = el("button", { className: "chat-bubble", title: "Ask a question" });
  bubble.innerHTML =
    '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"/></svg>';

  var panel = el("div", { className: "chat-panel" });

  var header = el("div", { className: "chat-header" });
  header.innerHTML = '<span>Ask about this page</span>';
  var clearBtn = el("button", { className: "chat-clear-btn", title: "Clear conversation" });
  clearBtn.textContent = "\u21BB";
  var closeBtn = el("button", {});
  closeBtn.textContent = "\u2715";
  header.appendChild(clearBtn);
  header.appendChild(closeBtn);

  var messages = el("div", { className: "chat-messages" });
  var inputArea = el("div", { className: "chat-input-area" });
  var input = el("input", { type: "text", placeholder: "Type your question\u2026" });
  var sendBtn = el("button", {});
  sendBtn.textContent = "Send";

  inputArea.appendChild(input);
  inputArea.appendChild(sendBtn);
  panel.appendChild(header);
  panel.appendChild(messages);
  panel.appendChild(inputArea);

  document.body.appendChild(bubble);
  document.body.appendChild(panel);

  // ── Events ──
  bubble.addEventListener("click", function () {
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) input.focus();
  });
  closeBtn.addEventListener("click", function () {
    panel.classList.remove("open");
  });
  clearBtn.addEventListener("click", clearMemory);
  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  function send() {
    var text = input.value.trim();
    if (!text || isStreaming) return;
    input.value = "";
    appendMsg("user", text);
    streamAnswer(text);
  }

  function clearMemory() {
    sessionId = null;
    localStorage.removeItem(SESSION_KEY);
    messages.innerHTML = "";
    var notice = el("div", { className: "chat-msg assistant" });
    notice.textContent = "Conversation cleared.";
    messages.appendChild(notice);
  }

  function streamAnswer(question) {
    isStreaming = true;
    sendBtn.disabled = true;

    var typingEl = el("div", { className: "chat-typing" });
    typingEl.textContent = "Thinking\u2026";
    messages.appendChild(typingEl);
    scrollBottom();

    var url = apiBase + "/api/chat/" + presentationId;
    var body = JSON.stringify({ message: question, session_id: sessionId });

    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body,
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        if (typingEl.parentNode) typingEl.remove();

        var assistantEl = appendMsg("assistant", "");
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        var fullText = "";
        var currentEvent = "";

        function read() {
          reader.read().then(function (result) {
            if (result.done) {
              finish();
              return;
            }
            buffer += decoder.decode(result.value, { stream: true });
            var lines = buffer.split("\n");
            buffer = lines.pop();

            for (var i = 0; i < lines.length; i++) {
              var line = lines[i];

              // SSE blank line = end of event block
              if (line.trim() === "") continue;

              // Track current SSE event type
              if (line.indexOf("event:") === 0) {
                currentEvent = line.substring(6).trim();
                if (currentEvent === "done") { finish(); return; }
                continue;
              }

              if (line.indexOf("data:") === 0) {
                // Strip "data:" prefix and exactly one optional space per SSE spec
                var data = line.substring(5);
                if (data.charAt(0) === " ") data = data.substring(1);

                if (currentEvent === "session") {
                  sessionId = data.trim();
                  localStorage.setItem(SESSION_KEY, sessionId);
                  currentEvent = "";
                  continue;
                }

                if (currentEvent === "error") {
                  fullText = "Sorry, an error occurred. Please try again.";
                  assistantEl.innerHTML = renderInlineMd(fullText);
                  currentEvent = "";
                  continue;
                }

                // chunk or start — append text (preserving spaces)
                fullText += data;
                assistantEl.innerHTML = renderInlineMd(fullText);
                scrollBottom();
                currentEvent = "";
              }
            }
            read();
          });
        }
        read();

        function finish() {
          isStreaming = false;
          sendBtn.disabled = false;
          input.focus();
        }
      })
      .catch(function () {
        if (typingEl.parentNode) typingEl.remove();
        appendMsg("assistant", "Sorry, something went wrong. Please try again.");
        isStreaming = false;
        sendBtn.disabled = false;
      });
  }

  // ── Helpers ──
  function appendMsg(role, text) {
    var d = el("div", { className: "chat-msg " + role });
    d.innerHTML = role === "assistant" ? renderInlineMd(text) : escapeHtml(text);
    messages.appendChild(d);
    scrollBottom();
    return d;
  }

  function scrollBottom() {
    messages.scrollTop = messages.scrollHeight;
  }

  function el(tag, attrs) {
    var e = document.createElement(tag);
    for (var k in attrs) e[k] = attrs[k];
    return e;
  }

  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function renderInlineMd(text) {
    var s = escapeHtml(text);
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
    s = s.replace(/`(.+?)`/g, "<code>$1</code>");
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/\n/g, "<br>");
    return s;
  }
})();
