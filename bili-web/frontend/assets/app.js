const state = {
  parsed: null,
  currentUrl: "",
  currentTask: null,
  taskTimer: null,
  listTimer: null,
  loginSessionId: null,
  loginTimer: null,
  loginMobileUrl: "",
};

const $ = (id) => document.getElementById(id);
const openedAsFile = window.location.protocol === "file:";

const statusLabels = {
  queued: "排队中",
  parsing: "解析中",
  downloading: "下载中",
  merging: "合并中",
  completed: "已完成",
  failed: "失败",
  canceled: "已取消",
};

const finalStatuses = new Set(["completed", "failed", "canceled"]);

const ui = {
  setService(status, online = false) {
    $("serviceStatus").textContent = status;
    $("serviceDot").classList.toggle("is-online", online);
  },

  setBusy(button, busy, textWhenBusy, textWhenIdle) {
    button.disabled = busy;
    button.textContent = busy ? textWhenBusy : textWhenIdle;
  },

  toast(message) {
    const toast = $("toast");
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(ui.toastTimer);
    ui.toastTimer = setTimeout(() => {
      toast.hidden = true;
    }, 2800);
  },

  setLoginBadge(text, ok = false) {
    $("loginBadge").textContent = text;
    $("loginBadge").classList.toggle("is-ok", ok);
  },
};

const api = {
  async request(path, options = {}) {
    if (openedAsFile) throw new Error("请通过 http://localhost 或你的域名访问网页。");
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "请求失败");
    return payload;
  },

  health: () => api.request("/api/health"),
  parse: (body) => api.request("/api/parse", jsonOptions(body)),
  checkCookie: (body) => api.request("/api/cookie/check", jsonOptions(body)),
  createQr: () => api.request("/api/login/qrcode", jsonOptions({})),
  pollLogin: (body) => api.request("/api/login/poll", jsonOptions(body)),
  download: (body) => api.request("/api/download", jsonOptions(body)),
  task: (taskId) => api.request(`/api/tasks/${taskId}`),
  tasks: () => api.request("/api/tasks"),
  cancelTask: (taskId) => api.request(`/api/tasks/${taskId}/cancel`, jsonOptions({})),
  cleanup: () => api.request("/api/tasks/cleanup", jsonOptions({})),
};

function jsonOptions(body) {
  return { method: "POST", body: JSON.stringify(body) };
}

function getBiliCookie() {
  return $("biliCookie").value.trim();
}

function setBiliCookie(cookie) {
  $("biliCookie").value = cookie || "";
  renderCookieFormat();
}

function normalizeLoginUrl(url) {
  if (!url) return "";
  if (url.startsWith("//")) return `https:${url}`;
  if (url.startsWith("/")) return `https://passport.bilibili.com${url}`;
  return url;
}

function proxiedImageUrl(url) {
  if (!url) return "";
  const normalized = url.startsWith("//") ? `https:${url}` : url.replace(/^http:\/\//, "https://");
  return `/api/image/proxy?url=${encodeURIComponent(normalized)}`;
}

function proxiedDownloadImageUrl(url, filename) {
  if (!url) return "";
  return `${proxiedImageUrl(url)}&download=1&filename=${encodeURIComponent(filename || "cover")}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function formatBytes(bytes = 0) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 100 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDuration(seconds) {
  if (!seconds) return "-";
  const hour = Math.floor(seconds / 3600);
  const minute = Math.floor((seconds % 3600) / 60);
  const second = seconds % 60;
  return hour ? `${hour}:${String(minute).padStart(2, "0")}:${String(second).padStart(2, "0")}` : `${minute}:${String(second).padStart(2, "0")}`;
}

function formatEta(seconds) {
  if (!seconds) return "剩余：-";
  if (seconds < 60) return `剩余：${seconds} 秒`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `剩余：${minutes} 分钟`;
  return `剩余：${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`;
}

function validateCookie(cookie) {
  if (!cookie) return { ok: false, message: "未填写 Cookie" };
  const required = ["SESSDATA", "bili_jct", "DedeUserID"];
  const missing = required.filter((key) => !cookie.includes(`${key}=`));
  return missing.length
    ? { ok: false, message: `缺少：${missing.join("、")}` }
    : { ok: true, message: "格式看起来完整" };
}

function renderCookieFormat() {
  const result = validateCookie(getBiliCookie());
  $("cookieFormat").textContent = result.message;
  $("cookieFormat").classList.toggle("is-ok", result.ok);
}

async function checkHealth() {
  if (openedAsFile) {
    ui.setService("需启动后端", false);
    return;
  }
  try {
    const data = await api.health();
    ui.setService("在线", true);
    $("retentionText").textContent = `文件默认保留 ${data.retention_hours || 24} 小时，过期自动清理。`;
  } catch {
    ui.setService("后端离线", false);
  }
}

function renderParsed(data) {
  state.parsed = data;
  $("resultPanel").hidden = false;
  $("cover").src = proxiedImageUrl(data.cover);
  $("cover").classList.toggle("is-empty", !data.cover);
  $("cover").onerror = () => {
    $("cover").removeAttribute("src");
    $("cover").classList.add("is-empty");
  };
  $("coverDownload").hidden = !data.cover;
  $("coverDownload").href = proxiedDownloadImageUrl(data.cover, `${data.bvid || "bilibili"}-cover`);
  $("coverDownload").download = `${data.bvid || "bilibili"}-cover.jpg`;
  $("title").textContent = data.title;
  $("meta").textContent = `${data.owner || "未知 UP"} · ${data.bvid}`;
  $("videoDuration").textContent = `时长：${formatDuration(data.duration)}`;
  $("pageCount").textContent = `分 P：${data.page_count || data.pages.length}`;
  $("qualitySummary").textContent = `清晰度：${data.quality_summary || "自动"}`;
  $("loginHint").textContent = data.requires_login_for_high_quality ? "高清：建议登录后下载" : "高清：当前可用";
  $("loginHint").classList.toggle("warn", Boolean(data.requires_login_for_high_quality));

  $("pageSelect").innerHTML = data.pages
    .map((item) => `<option value="${item.page}" ${item.page === data.selected_page ? "selected" : ""}>P${item.page} ${escapeHtml(item.title)} · ${formatDuration(item.duration)}</option>`)
    .join("");

  $("qualitySelect").innerHTML = data.video_streams.length
    ? data.video_streams.map((item) => `<option value="${item.id}">${item.label}</option>`).join("")
    : `<option value="">自动</option>`;

  $("downloadBtn").disabled = false;
}

async function parseVideo(page = null) {
  if (!state.currentUrl) return;
  const data = await api.parse({
    url: state.currentUrl,
    page,
    bili_cookie: getBiliCookie() || null,
  });
  renderParsed(data);
}

function watchTask(taskId) {
  state.currentTask = taskId;
  $("taskPanel").hidden = false;
  $("fileLink").hidden = true;
  clearInterval(state.taskTimer);
  pollTask();
  state.taskTimer = setInterval(pollTask, 1500);
  refreshTasks();
  startTaskListPolling();
}

async function pollTask() {
  if (!state.currentTask) return;
  try {
    const task = await api.task(state.currentTask);
    renderCurrentTask(task);
    if (finalStatuses.has(task.status)) {
      clearInterval(state.taskTimer);
      $("downloadBtn").disabled = false;
      refreshTasks();
    }
  } catch (error) {
    clearInterval(state.taskTimer);
    $("downloadBtn").disabled = false;
    $("taskMessage").textContent = error.message;
  }
}

function renderCurrentTask(task) {
  const label = statusLabels[task.status] || task.status;
  $("taskTitle").textContent = task.title || task.id;
  $("taskStatus").textContent = `${label} · ${task.progress}%`;
  $("taskMessage").textContent = task.message || "";
  $("progressBar").style.width = `${Math.max(0, Math.min(task.progress, 100))}%`;
  $("taskSize").textContent = `${formatBytes(task.downloaded_bytes)} / ${formatBytes(task.total_bytes)}`;
  $("taskSpeed").textContent = task.status === "completed" ? "已就绪" : `${formatBytes(task.speed_bytes)}/s`;
  $("taskEta").textContent = formatEta(task.eta_seconds);
  $("cancelCurrentBtn").disabled = finalStatuses.has(task.status);

  if (task.status === "completed") {
    $("fileLink").hidden = false;
    $("fileLink").href = task.download_url;
    $("fileLink").download = task.file_name || "";
  }
}

async function refreshTasks() {
  try {
    const data = await api.tasks();
    $("retentionText").textContent = `文件默认保留 ${data.retention_hours} 小时，过期自动清理。`;
    renderTaskList(data.tasks || []);
  } catch (error) {
    $("taskList").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function renderTaskList(tasks) {
  if (!tasks.length) {
    $("taskList").innerHTML = `<div class="empty-state">暂无任务</div>`;
    return;
  }

  $("taskList").innerHTML = tasks.map((task) => {
    const label = statusLabels[task.status] || task.status;
    const canCancel = !finalStatuses.has(task.status);
    const download = task.download_url ? `<a class="mini-link" href="${task.download_url}" download="${escapeHtml(task.file_name || "")}">保存</a>` : "";
    const cancel = canCancel ? `<button class="mini-danger" data-cancel="${task.id}" type="button">取消</button>` : "";
    return `
      <article class="task-item">
        <div class="task-item-head">
          <strong>${escapeHtml(task.title || task.id)}</strong>
          <span class="task-status ${task.status}">${label}</span>
        </div>
        <div class="mini-progress"><span style="width:${Math.max(0, Math.min(task.progress, 100))}%"></span></div>
        <div class="task-item-meta">
          <span>${task.progress}%</span>
          <span>${formatBytes(task.downloaded_bytes)} / ${formatBytes(task.total_bytes)}</span>
          <span>${formatBytes(task.speed_bytes)}/s</span>
          <span>${formatEta(task.eta_seconds)}</span>
        </div>
        <p>${escapeHtml(task.message || "")}</p>
        <div class="task-actions">${download}${cancel}</div>
      </article>
    `;
  }).join("");
}

function startTaskListPolling() {
  clearInterval(state.listTimer);
  state.listTimer = setInterval(refreshTasks, 3000);
}

async function createQrLogin() {
  const button = $("createQrBtn");
  ui.setBusy(button, true, "生成中", "扫码登录");
  clearInterval(state.loginTimer);
  $("qrStatus").textContent = "正在生成二维码";
  $("qrBox").innerHTML = "<span>生成中</span>";

  try {
    const result = await api.createQr();
    state.loginSessionId = result.session_id;
    state.loginMobileUrl = normalizeLoginUrl(result.qrcode_url);
    $("qrBox").innerHTML = `<img src="${result.qrcode_image}" alt="B站扫码登录二维码" />`;
    $("mobileLoginBtn").hidden = false;
    $("copyLoginUrlBtn").hidden = false;
    $("qrStatus").textContent = "电脑扫码，手机可打开登录链接";
    state.loginTimer = setInterval(pollLogin, 1500);
  } catch (error) {
    $("qrStatus").textContent = error.message;
  } finally {
    ui.setBusy(button, false, "生成中", "扫码登录");
  }
}

async function pollLogin() {
  if (!state.loginSessionId) return;
  try {
    const result = await api.pollLogin({ session_id: state.loginSessionId });
    $("qrStatus").textContent = result.message || "等待扫码";
    if (result.is_login) {
      clearInterval(state.loginTimer);
      state.loginTimer = null;
      setBiliCookie(result.bili_cookie);
      $("qrStatus").textContent = "扫码登录成功，Cookie 已填入";
      await checkCookie();
    }
    if (result.code === 86038) {
      clearInterval(state.loginTimer);
      state.loginTimer = null;
    }
  } catch (error) {
    clearInterval(state.loginTimer);
    state.loginTimer = null;
    $("qrStatus").textContent = error.message;
  }
}

async function checkCookie() {
  const result = await api.checkCookie({ bili_cookie: getBiliCookie() || null });
  const ok = Boolean(result.is_login);
  $("cookieCheckResult").textContent = ok ? `已登录：${result.uname || result.mid}` : (result.message || "未登录：Cookie 无效、复制不完整，或已过期。");
  ui.setLoginBadge(ok ? "已登录" : "未登录", ok);
  renderProfile(result);
  return result;
}

function renderProfile(result) {
  $("profileBox").hidden = !result.is_login;
  if (!result.is_login) return;
  $("profileFace").src = proxiedImageUrl(result.face);
  $("profileFace").onerror = () => {
    $("profileFace").removeAttribute("src");
    $("profileFace").classList.add("is-empty");
  };
  $("profileFace").classList.toggle("is-empty", !result.face);
  $("profileName").textContent = result.uname || "已登录";
  $("profileMid").textContent = result.mid ? `UID ${result.mid}` : "";
}

function bindEvents() {
  $("parseForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.currentUrl = $("videoUrl").value.trim();
    ui.setBusy($("parseBtn"), true, "解析中", "解析");
    try {
      await parseVideo();
    } catch (error) {
      ui.toast(error.message);
    } finally {
      ui.setBusy($("parseBtn"), false, "解析中", "解析");
    }
  });

  $("pageSelect").addEventListener("change", async () => {
    try {
      await parseVideo(Number($("pageSelect").value));
    } catch (error) {
      ui.toast(error.message);
    }
  });

  $("downloadBtn").addEventListener("click", async () => {
    if (!state.currentUrl) return;
    $("downloadBtn").disabled = true;
    try {
      const qualityValue = $("qualitySelect").value;
      const task = await api.download({
        url: state.currentUrl,
        page: Number($("pageSelect").value),
        quality: qualityValue ? Number(qualityValue) : null,
        kind: $("kindSelect").value,
        bili_cookie: getBiliCookie() || null,
      });
      watchTask(task.id);
    } catch (error) {
      ui.toast(error.message);
      $("downloadBtn").disabled = false;
    }
  });

  $("cancelCurrentBtn").addEventListener("click", async () => {
    if (!state.currentTask) return;
    await api.cancelTask(state.currentTask);
    await pollTask();
    await refreshTasks();
  });

  $("taskList").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-cancel]");
    if (!button) return;
    await api.cancelTask(button.dataset.cancel);
    await refreshTasks();
  });

  $("refreshTasksBtn").addEventListener("click", refreshTasks);

  $("cleanupBtn").addEventListener("click", async () => {
    const result = await api.cleanup();
    ui.toast(`已清理 ${result.removed || 0} 个过期文件`);
    await refreshTasks();
  });

  $("createQrBtn").addEventListener("click", createQrLogin);

  $("mobileLoginBtn").addEventListener("click", () => {
    if (!state.loginMobileUrl) {
      $("qrStatus").textContent = "请先生成登录链接";
      return;
    }
    window.location.href = state.loginMobileUrl;
  });

  $("copyLoginUrlBtn").addEventListener("click", async () => {
    if (!state.loginMobileUrl) {
      $("qrStatus").textContent = "请先生成登录链接";
      return;
    }
    try {
      await navigator.clipboard.writeText(state.loginMobileUrl);
      $("qrStatus").textContent = "登录链接已复制";
    } catch {
      $("qrStatus").textContent = state.loginMobileUrl;
    }
  });

  $("stopQrBtn").addEventListener("click", () => {
    clearInterval(state.loginTimer);
    state.loginTimer = null;
    $("qrStatus").textContent = "已停止轮询";
  });

  $("biliCookie").addEventListener("input", renderCookieFormat);

  $("checkCookieBtn").addEventListener("click", async () => {
    const button = $("checkCookieBtn");
    const format = validateCookie(getBiliCookie());
    if (!format.ok) {
      $("cookieCheckResult").textContent = format.message;
      ui.setLoginBadge("未登录", false);
      return;
    }
    ui.setBusy(button, true, "检查中", "检查 Cookie");
    $("cookieCheckResult").textContent = "检查中";
    try {
      await checkCookie();
    } catch (error) {
      $("cookieCheckResult").textContent = `检查失败：${error.message}`;
      ui.setLoginBadge("未登录", false);
    } finally {
      ui.setBusy(button, false, "检查中", "检查 Cookie");
    }
  });

  $("clearCookieBtn").addEventListener("click", () => {
    setBiliCookie("");
    $("cookieCheckResult").textContent = "";
    $("profileBox").hidden = true;
    ui.setLoginBadge("未登录", false);
  });
}

bindEvents();
renderCookieFormat();
checkHealth();
refreshTasks();
startTaskListPolling();
