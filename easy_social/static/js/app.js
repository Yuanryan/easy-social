(function () {
  function mediaKind(file) {
    if (file.type.startsWith("image/")) {
      return "image";
    }
    if (file.type.startsWith("video/")) {
      return "video";
    }

    const extension = file.name.split(".").pop().toLowerCase();
    if (["gif", "jpg", "jpeg", "png", "webp"].includes(extension)) {
      return "image";
    }
    if (["mov", "mp4", "ogg", "webm"].includes(extension)) {
      return "video";
    }
    return "";
  }

  function clearPreview(preview, frame, name, input, state) {
    if (state.objectUrl) {
      URL.revokeObjectURL(state.objectUrl);
      state.objectUrl = "";
    }
    frame.replaceChildren();
    name.textContent = "";
    preview.hidden = true;
    if (input) {
      input.value = "";
    }
  }

  function setupComposer(composer) {
    const input = composer.querySelector("[data-media-input]");
    const preview = composer.querySelector("[data-media-preview]");
    const frame = composer.querySelector("[data-media-preview-frame]");
    const name = composer.querySelector("[data-media-preview-name]");
    const clear = composer.querySelector("[data-media-preview-clear]");

    if (!input || !preview || !frame || !name || !clear) {
      return;
    }

    const state = { objectUrl: "" };

    input.addEventListener("change", function () {
      const file = input.files && input.files[0];
      clearPreview(preview, frame, name, null, state);

      if (!file) {
        return;
      }

      const kind = mediaKind(file);
      if (!kind) {
        return;
      }

      state.objectUrl = URL.createObjectURL(file);
      const element = document.createElement(kind === "image" ? "img" : "video");
      element.className = "composer-preview-media";
      element.src = state.objectUrl;

      if (kind === "image") {
        element.alt = "Selected image preview";
      } else {
        element.controls = true;
        element.muted = true;
        element.preload = "metadata";
      }

      frame.replaceChildren(element);
      name.textContent = file.name;
      preview.hidden = false;
    });

    clear.addEventListener("click", function () {
      clearPreview(preview, frame, name, input, state);
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  function setupPollComposer(composer) {
    const toggle = composer.querySelector("[data-poll-toggle]");
    const panel = composer.querySelector("[data-poll-composer]");
    const flag = composer.querySelector("[data-poll-flag]");
    const list = composer.querySelector("[data-poll-options]");
    const add = composer.querySelector("[data-poll-add]");
    const remove = composer.querySelector("[data-poll-remove]");
    if (!toggle || !panel || !flag || !list || !add || !remove) {
      return;
    }

    function setActive(active) {
      panel.hidden = !active;
      flag.disabled = !active;
      toggle.hidden = active;
    }

    function refreshAddState() {
      const inputs = list.querySelectorAll("input[name='poll_option']");
      add.disabled = inputs.length >= 4;
    }

    setActive(false);
    refreshAddState();

    toggle.addEventListener("click", function () {
      setActive(true);
    });

    add.addEventListener("click", function () {
      const inputs = list.querySelectorAll("input[name='poll_option']");
      if (inputs.length >= 4) {
        return;
      }
      const li = document.createElement("li");
      const input = document.createElement("input");
      input.type = "text";
      input.name = "poll_option";
      input.maxLength = 80;
      input.placeholder = "Option " + (inputs.length + 1);
      li.appendChild(input);
      list.appendChild(li);
      refreshAddState();
    });

    remove.addEventListener("click", function () {
      list.innerHTML =
        '<li><input type="text" name="poll_option" maxlength="80" placeholder="Option 1"></li>' +
        '<li><input type="text" name="poll_option" maxlength="80" placeholder="Option 2"></li>';
      setActive(false);
      refreshAddState();
    });
  }

  function applyPollResults(poll, results) {
    const options = poll.querySelectorAll("[data-poll-option-id]");
    const totalEl = poll.querySelector("[data-poll-total]");
    if (totalEl) {
      totalEl.textContent = String(results.total);
    }
    options.forEach(function (li) {
      const id = Number(li.getAttribute("data-poll-option-id"));
      const data = results.options.find(function (o) {
        return o.id === id;
      });
      if (!data) {
        return;
      }
      const ratio = (data.ratio || 0) * 100;
      const bar = li.querySelector("[data-poll-bar]");
      const ratioEl = li.querySelector("[data-poll-ratio]");
      if (bar) {
        bar.style.width = ratio.toFixed(1) + "%";
      }
      if (ratioEl) {
        ratioEl.textContent = ratio.toFixed(1) + "%";
      }
      if (results.viewer_option_id === id) {
        li.classList.add("poll-option-chosen");
      } else {
        li.classList.remove("poll-option-chosen");
      }
    });
  }

  function setupPoll(poll) {
    const voteUrl = poll.getAttribute("data-poll-vote-url");
    if (!voteUrl) {
      return;
    }
    poll.querySelectorAll("[data-poll-vote]").forEach(function (button) {
      button.addEventListener("click", function () {
        const li = button.closest("[data-poll-option-id]");
        if (!li) {
          return;
        }
        const optionId = li.getAttribute("data-poll-option-id");
        const formData = new FormData();
        formData.append("option_id", optionId);
        fetch(voteUrl, {
          method: "POST",
          body: formData,
          credentials: "same-origin",
        })
          .then(function (response) {
            if (response.redirected) {
              window.location.href = response.url;
              return null;
            }
            if (response.status === 401) {
              window.location.href = "/auth/login";
              return null;
            }
            const contentType = response.headers.get("content-type") || "";
            if (!contentType.includes("application/json")) {
              return null;
            }
            return response.json();
          })
          .then(function (data) {
            if (data && !data.error) {
              applyPollResults(poll, data);
            }
          });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form.composer").forEach(setupComposer);
    document.querySelectorAll("form.composer").forEach(setupPollComposer);
    document.querySelectorAll("[data-poll]").forEach(setupPoll);
  });
})();
