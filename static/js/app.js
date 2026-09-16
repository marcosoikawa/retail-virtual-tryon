/* ==========================================================================
   Virtual Try-On — front-end vanilla
   ========================================================================== */

(() => {
  "use strict";

  const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
  const LOADING_MESSAGES = [
    "Analisando a silhueta do modelo…",
    "Lendo estampas, cores e texturas…",
    "Analisando o caimento das peças…",
    "Ajustando dobras, sombras e iluminação…",
    "Finalizando o acabamento da imagem…",
  ];
  const SIMULATOR_STORAGE_KEY = "vto-scale-assumptions-v2";
  const DEFAULT_MONTHLY_AI_SESSIONS = 67_500;
  const LUNA_INPUT_PRICE_PER_1M = 0.20;
  const LUNA_CACHED_INPUT_PRICE_PER_1M = 0.02;
  const LUNA_CACHE_WRITE_PRICE_PER_1M = 0.25;
  const LUNA_OUTPUT_PRICE_PER_1M = 1.20;

  const body = document.body;
  const MAX_GARMENTS = Number(body.dataset.maxGarments || 5);
  const MAX_BYTES = Number(body.dataset.maxUploadMb || 10) * 1024 * 1024;

  const $ = (id) => document.getElementById(id);

  /* --------------------------------------------------------------- debug */

  const debug = {
    entries: [],
    max: 300,
    unseen: 0,
    log: null,
    badge: null,
    autoscroll: null,
  };

  function debugLog(level, ...parts) {
    const message = parts
      .map((part) => {
        if (part instanceof Error) return part.stack || `${part.name}: ${part.message}`;
        if (typeof part === "object") {
          try { return JSON.stringify(part); } catch { return String(part); }
        }
        return String(part);
      })
      .join(" ");
    const entry = { time: new Date(), level, message };
    debug.entries.push(entry);
    if (debug.entries.length > debug.max) debug.entries.shift();
    renderDebugEntry(entry);
    if (debug.badge && (!debug.body || debug.body.hidden)) {
      debug.unseen += 1;
      debug.badge.hidden = false;
      debug.badge.textContent = String(debug.unseen);
      debug.badge.classList.toggle("debug-badge--alert", level === "error");
    }
  }

  function renderDebugEntry(entry) {
    if (!debug.log) return;
    const empty = debug.log.querySelector(".debug-log__empty");
    if (empty) empty.remove();
    const line = document.createElement("div");
    line.className = `debug-line debug-line--${entry.level}`;
    const stamp = entry.time.toLocaleTimeString("pt-BR", { hour12: false });
    line.innerHTML =
      `<span class="debug-line__time">${stamp}</span>` +
      `<span class="debug-line__level">${entry.level.toUpperCase()}</span>`;
    const text = document.createElement("span");
    text.className = "debug-line__msg";
    text.textContent = entry.message;
    line.appendChild(text);
    debug.log.appendChild(line);
    if (!debug.autoscroll || debug.autoscroll.checked) {
      debug.log.scrollTop = debug.log.scrollHeight;
    }
  }

  window.addEventListener("error", (event) => {
    debugLog("error", event.message, event.filename ? `(${event.filename}:${event.lineno})` : "");
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    debugLog("error", "Promise rejeitada:", reason instanceof Error ? reason : String(reason));
  });
  ["error", "warn"].forEach((method) => {
    const original = console[method].bind(console);
    console[method] = (...args) => {
      debugLog(method === "warn" ? "warn" : "error", ...args);
      original(...args);
    };
  });

  const el = {
    themeToggle: $("themeToggle"),
    navApp: $("navApp"),
    navDashboard: $("navDashboard"),
    personDropzone: $("personDropzone"),
    personInput: $("personInput"),
    personEmpty: $("personEmpty"),
    personPreview: $("personPreview"),
    personImage: $("personImage"),
    personRemove: $("personRemove"),
    garmentDropzone: $("garmentDropzone"),
    garmentInput: $("garmentInput"),
    garmentGrid: $("garmentGrid"),
    garmentCount: $("garmentCount"),
    backgroundSelect: $("backgroundSelect"),
    styleSelect: $("styleSelect"),
    notesInput: $("notesInput"),
    generateBtn: $("generateBtn"),
    panelPhoto: $("panelPhoto"),
    statusLive: $("statusLive"),
    photoEmpty: $("photoEmpty"),
    photoLoading: $("photoLoading"),
    photoLoadingText: $("photoLoadingText"),
    photoProgressBar: $("photoProgressBar"),
    photoResult: $("photoResult"),
    photoActions: $("photoActions"),
    resultImage: $("resultImage"),
    compareWrap: $("compareWrap"),
    compareLayer: $("compareLayer"),
    compareBefore: $("compareBefore"),
    compareHandle: $("compareHandle"),
    downloadBtn: $("downloadBtn"),
    compareBtn: $("compareBtn"),
    regenerateBtn: $("regenerateBtn"),
    galleryStrip: $("galleryStrip"),
    galleryHint: $("galleryHint"),
    metricsToggle: $("metricsToggle"),
    metricsBody: $("metricsBody"),
    refreshMetricsBtn: $("refreshMetricsBtn"),
    metricsGrid: $("metricsGrid"),
    metricAverage: $("metricAverage"),
    metricP95: $("metricP95"),
    metricSuccess: $("metricSuccess"),
    metricErrors: $("metricErrors"),
    metricRequests: $("metricRequests"),
    metricImages: $("metricImages"),
    metricUptime: $("metricUptime"),
    metricUpdated: $("metricUpdated"),
    metricsRoutes: $("metricsRoutes"),
    metricTokens: $("metricTokens"),
    metricTokensBreak: $("metricTokensBreak"),
    metricCost: $("metricCost"),
    metricCostPerImage: $("metricCostPerImage"),
    dashboardRefreshBtn: $("dashboardRefreshBtn"),
    dashboardMode: $("dashboardMode"),
    executionResults: $("executionResults"),
    executionRows: $("executionRows"),
    executionCount: $("executionCount"),
    selectAllExecutions: $("selectAllExecutions"),
    dashGrid: $("dashGrid"),
    dashLooks: $("dashLooks"),
    dashAvgTime: $("dashAvgTime"),
    dashP95Time: $("dashP95Time"),
    dashSuccess: $("dashSuccess"),
    dashErrors: $("dashErrors"),
    dashObservedAt: $("dashObservedAt"),
    dashExecutiveSummary: $("dashExecutiveSummary"),
    dashTokens: $("dashTokens"),
    dashTokensPerLook: $("dashTokensPerLook"),
    dashTokensBreak: $("dashTokensBreak"),
    dashCostTotal: $("dashCostTotal"),
    dashCostPer: $("dashCostPer"),
    costImage: $("costImage"),
    dashInputMegapixels: $("dashInputMegapixels"),
    dashOutputMegapixels: $("dashOutputMegapixels"),
    recentList: $("recentList"),
    scaleControls: $("scaleControls"),
    scaleVolume: $("scaleVolume"),
    scaleLooksPerSession: $("scaleLooksPerSession"),
    scaleMonthlyLooks: $("scaleMonthlyLooks"),
    scaleCacheEnabled: $("scaleCacheEnabled"),
    scaleExchangeRate: $("scaleExchangeRate"),
    scaleImageCost: $("scaleImageCost"),
    scaleBaselineCost: $("scaleBaselineCost"),
    scaleMonthlyCost: $("scaleMonthlyCost"),
    scaleAnnualCost: $("scaleAnnualCost"),
    scaleCostPerJourney: $("scaleCostPerJourney"),
    scaleCoverage: $("scaleCoverage"),
    scaleAdditionalCoverage: $("scaleAdditionalCoverage"),
    scaleMonthlySavings: $("scaleMonthlySavings"),
    scaleAnnualSavings: $("scaleAnnualSavings"),
    scaleSavingsRate: $("scaleSavingsRate"),
    scaleSourceNote: $("scaleSourceNote"),
    lunaControls: $("lunaControls"),
    lunaMonthlySessions: $("lunaMonthlySessions"),
    lunaInputTokens: $("lunaInputTokens"),
    lunaOutputTokens: $("lunaOutputTokens"),
    lunaCachedShare: $("lunaCachedShare"),
    lunaCacheWriteTokens: $("lunaCacheWriteTokens"),
    lunaCurrentCached: $("lunaCurrentCached"),
    lunaCurrentUncached: $("lunaCurrentUncached"),
    lunaCurrentCachedPerSession: $("lunaCurrentCachedPerSession"),
    lunaCurrentCachedMonthly: $("lunaCurrentCachedMonthly"),
    lunaCachedPerSession: $("lunaCachedPerSession"),
    lunaCachedMonthly: $("lunaCachedMonthly"),
    lunaCurrentUncachedPerSession: $("lunaCurrentUncachedPerSession"),
    lunaCurrentUncachedMonthly: $("lunaCurrentUncachedMonthly"),
    lunaUncachedPerSession: $("lunaUncachedPerSession"),
    lunaUncachedMonthly: $("lunaUncachedMonthly"),
    lunaCachedSavings: $("lunaCachedSavings"),
    lunaUncachedSavings: $("lunaUncachedSavings"),
    lunaSourceNote: $("lunaSourceNote"),
    debugToggle: $("debugToggle"),
    debugBody: $("debugBody"),
    debugBadge: $("debugBadge"),
    debugLog: $("debugLog"),
    debugAutoscroll: $("debugAutoscroll"),
    debugCopyBtn: $("debugCopyBtn"),
    debugClearBtn: $("debugClearBtn"),
    toasts: $("toasts"),
  };

  const state = {
    person: null,
    personUrl: null,
    garments: [],
    current: null,
    gallery: [],
    messageTimer: null,
    photoProgressTimer: null,
    isGenerating: false,
    compareOn: false,
    metricsTimer: null,
    lastMetrics: null,
    selectedExecutionIds: new Set(),
    dashboardSelectAll: true,
  };

  /* ---------------------------------------------------------------- utils */

  const announce = (message) => {
    el.statusLive.textContent = message;
  };

  function toast(message, kind = "info", timeout = 5000) {
    if (kind === "error" || kind === "success") {
      debugLog(kind === "error" ? "error" : "info", message);
    }
    const node = document.createElement("div");
    node.className = `toast toast--${kind}`;
    node.setAttribute("role", kind === "error" ? "alert" : "status");
    node.textContent = message;
    el.toasts.appendChild(node);
    window.setTimeout(() => {
      node.classList.add("is-leaving");
      window.setTimeout(() => node.remove(), 260);
    }, timeout);
  }

  function formatClock(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const minutes = String(Math.floor(total / 60)).padStart(2, "0");
    const seconds = String(total % 60).padStart(2, "0");
    return `${minutes}:${seconds}`;
  }

  function formatDuration(ms) {
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
  }

  function formatUptime(seconds) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days) return `${days}d ${hours}h`;
    if (hours) return `${hours}h ${minutes}min`;
    return `${minutes}min`;
  }

  function formatCount(value) {
    return Number(value || 0).toLocaleString("pt-BR");
  }

  function formatTokens(value) {
    const n = Number(value || 0);
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return String(n);
  }

  function formatUSD(value) {
    const n = Number(value || 0);
    const digits = n > 0 && n < 0.01 ? 4 : 2;
    return new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(n);
  }

  function formatBRL(value) {
    return new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency: "BRL",
      maximumFractionDigits: 2,
    }).format(Number(value || 0));
  }

  function validateFile(file) {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return `"${file.name}" não é um formato suportado. Use JPG, PNG ou WEBP.`;
    }
    if (file.size > MAX_BYTES) {
      return `"${file.name}" excede ${Math.round(MAX_BYTES / 1024 / 1024)} MB.`;
    }
    return null;
  }

  async function readError(response, fallback) {
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") return payload.detail;
      if (Array.isArray(payload.detail) && payload.detail.length) {
        return payload.detail[0].msg || fallback;
      }
    } catch (_) {
      /* corpo não-JSON */
    }
    return fallback;
  }

  /* ---------------------------------------------------------------- tema */

  function initTheme() {
    const stored = localStorage.getItem("vto-theme");
    document.documentElement.dataset.theme = stored || "light";
    el.themeToggle.addEventListener("click", () => {
      const root = document.documentElement;
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const currentIsDark =
        root.dataset.theme === "dark" || (root.dataset.theme === "auto" && prefersDark);
      const next = currentIsDark ? "light" : "dark";
      root.dataset.theme = next;
      localStorage.setItem("vto-theme", next);
    });
  }

  /* ------------------------------------------------------------- uploads */

  function bindDropzone(zone, input, handler) {
    zone.addEventListener("click", (event) => {
      if (event.target.closest(".chip-remove")) return;
      input.click();
    });
    zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });
    input.addEventListener("change", () => {
      handler(Array.from(input.files || []));
      input.value = "";
    });
    ["dragenter", "dragover"].forEach((type) =>
      zone.addEventListener(type, (event) => {
        event.preventDefault();
        zone.classList.add("is-dragover");
      })
    );
    ["dragleave", "drop"].forEach((type) =>
      zone.addEventListener(type, (event) => {
        event.preventDefault();
        if (type === "dragleave" && zone.contains(event.relatedTarget)) return;
        zone.classList.remove("is-dragover");
      })
    );
    zone.addEventListener("drop", (event) => {
      const files = Array.from(event.dataTransfer?.files || []);
      if (files.length) handler(files);
    });
  }

  function releasePersonUrl() {
    // Mantém a URL viva enquanto algum look do histórico ainda a usa no comparador.
    if (!state.personUrl) return;
    const stillUsed = state.gallery.some((item) => item.personUrl === state.personUrl);
    if (!stillUsed) URL.revokeObjectURL(state.personUrl);
  }

  function setPerson(files) {
    const file = files[0];
    if (!file) return;
    const error = validateFile(file);
    if (error) return toast(error, "error");

    releasePersonUrl();
    state.person = file;
    state.personUrl = URL.createObjectURL(file);
    el.personImage.src = state.personUrl;
    el.personEmpty.hidden = true;
    el.personPreview.hidden = false;
    updateGenerateButton();
  }

  function clearPerson() {
    releasePersonUrl();
    state.person = null;
    state.personUrl = null;
    el.personImage.removeAttribute("src");
    el.personEmpty.hidden = false;
    el.personPreview.hidden = true;
    updateGenerateButton();
  }

  function addGarments(files) {
    let rejected = 0;
    files.forEach((file) => {
      if (state.garments.length >= MAX_GARMENTS) {
        rejected += 1;
        return;
      }
      const error = validateFile(file);
      if (error) return toast(error, "error");
      state.garments.push({ file, url: URL.createObjectURL(file), id: crypto.randomUUID() });
    });
    if (rejected > 0) {
      toast(`Limite de ${MAX_GARMENTS} peças atingido.`, "error");
    }
    renderGarments();
  }

  function removeGarment(id) {
    const index = state.garments.findIndex((item) => item.id === id);
    if (index < 0) return;
    URL.revokeObjectURL(state.garments[index].url);
    state.garments.splice(index, 1);
    renderGarments();
  }

  function renderGarments() {
    el.garmentGrid.textContent = "";
    state.garments.forEach((item, index) => {
      const li = document.createElement("li");
      li.className = "thumb";

      const img = document.createElement("img");
      img.src = item.url;
      img.alt = `Peça ${index + 1}: ${item.file.name}`;

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "chip-remove";
      remove.setAttribute("aria-label", `Remover peça ${index + 1}`);
      remove.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
      remove.addEventListener("click", (event) => {
        event.stopPropagation();
        removeGarment(item.id);
      });

      li.append(img, remove);
      el.garmentGrid.appendChild(li);
    });

    el.garmentCount.textContent = String(state.garments.length);
    updateGenerateButton();
  }

  function updateGenerateButton() {
    el.generateBtn.disabled = !state.person || state.garments.length === 0 || state.isGenerating;
  }

  /* --------------------------------------------------------- geração foto */

  function startPhotoLoading() {
    el.photoEmpty.hidden = true;
    el.photoResult.hidden = true;
    el.photoActions.hidden = true;
    el.photoLoading.hidden = false;

    let progress = 4;
    el.photoProgressBar.style.width = "4%";
    state.photoProgressTimer = window.setInterval(() => {
      progress = Math.min(progress + Math.random() * 6, 92);
      el.photoProgressBar.style.width = `${progress}%`;
    }, 900);

    let index = 0;
    el.photoLoadingText.textContent = LOADING_MESSAGES[0];
    announce("Gerando a foto do look.");
    state.messageTimer = window.setInterval(() => {
      index = (index + 1) % LOADING_MESSAGES.length;
      el.photoLoadingText.textContent = LOADING_MESSAGES[index];
    }, 4200);
  }

  function stopPhotoLoading() {
    window.clearInterval(state.photoProgressTimer);
    window.clearInterval(state.messageTimer);
    el.photoProgressBar.style.width = "100%";
    el.photoLoading.hidden = true;
  }

  async function generateLook() {
    if (!state.person || state.garments.length === 0 || state.isGenerating) return;

    state.isGenerating = true;
    updateGenerateButton();
    el.generateBtn.classList.add("is-busy");
    startPhotoLoading();

    const form = new FormData();
    form.append("person", state.person, state.person.name);
    state.garments.forEach((item) => form.append("garments", item.file, item.file.name));
    form.append("image_model", "gpt-image-2");
    form.append("background", el.backgroundSelect.value);
    form.append("style", el.styleSelect.value);
    form.append("notes", el.notesInput.value);

    try {
      const response = await fetch("/api/tryon", { method: "POST", body: form });
      if (!response.ok) {
        throw new Error(await readError(response, "Não foi possível gerar o look."));
      }
      const data = await response.json();
      applyResult({
        imageId: data.image_id,
        imageUrl: data.image_url,
        dataUrl: data.image_data_url,
        personUrl: state.personUrl,
        orientation: data.suggested_orientation || "portrait",
      });
      addToGallery(state.current);
      toast(`Look gerado em ${(data.elapsed_ms / 1000).toFixed(1)}s.`, "success");
      debugLog(
        "info",
        `Look ${String(data.image_id).slice(0, 8)}: ${data.total_tokens || 0} tokens ` +
          `(${data.input_tokens || 0} entrada / ${data.output_tokens || 0} saída) em ${data.elapsed_ms}ms.`
      );
      announce("Foto do look pronta.");
      refreshDashboard();
    } catch (error) {
      el.photoLoading.hidden = true;
      if (!state.current) el.photoEmpty.hidden = false;
      toast(error.message, "error");
      announce("Falha ao gerar a foto.");
    } finally {
      stopPhotoLoading();
      state.isGenerating = false;
      el.generateBtn.classList.remove("is-busy");
      updateGenerateButton();
    }
  }

  function applyResult(item) {
    state.current = item;
    el.resultImage.src = item.dataUrl || item.imageUrl;
    el.resultImage.alt = "Foto gerada da pessoa vestindo as peças enviadas";
    el.photoResult.hidden = false;
    el.photoEmpty.hidden = true;
    el.photoActions.hidden = false;
    el.downloadBtn.href = item.imageUrl;
    el.downloadBtn.setAttribute("download", `look-${item.imageId}.png`);

    setCompare(false);
    el.compareBtn.disabled = !item.personUrl;
    if (item.personUrl) el.compareBefore.src = item.personUrl;

    highlightGallery();
  }

  /* ------------------------------------------------------------- comparar */

  function setCompare(active) {
    state.compareOn = active;
    el.compareLayer.hidden = !active;
    el.compareBtn.setAttribute("aria-pressed", String(active));
    el.compareBtn.textContent = active ? "Ocultar comparação" : "Comparar";
    if (active) setComparePosition(50);
  }

  function setComparePosition(percent) {
    const clamped = Math.min(100, Math.max(0, percent));
    el.compareWrap.style.setProperty("--compare-pos", `${clamped}%`);
    el.compareHandle.setAttribute("aria-valuenow", String(Math.round(clamped)));
  }

  function initCompare() {
    el.compareBtn.addEventListener("click", () => setCompare(!state.compareOn));

    const move = (clientX) => {
      const rect = el.compareWrap.getBoundingClientRect();
      setComparePosition(((clientX - rect.left) / rect.width) * 100);
    };

    el.compareLayer.addEventListener("pointerdown", (event) => {
      el.compareHandle.setPointerCapture?.(event.pointerId);
      move(event.clientX);
      const onMove = (moveEvent) => move(moveEvent.clientX);
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });

    el.compareHandle.addEventListener("keydown", (event) => {
      const current = Number(el.compareHandle.getAttribute("aria-valuenow") || 50);
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setComparePosition(current - 4);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setComparePosition(current + 4);
      }
    });
  }

  /* ------------------------------------------------------------- métricas */

  function toggleMetrics(force) {
    const open = typeof force === "boolean" ? force : el.metricsBody.hidden;
    el.metricsBody.hidden = !open;
    el.metricsToggle.setAttribute("aria-expanded", String(open));
    if (open) {
      loadMetrics();
      startMetricsRefresh();
    } else {
      stopMetricsRefresh();
    }
  }

  /* ---------------------------------------------------------------- debug */

  function toggleDebug(force) {
    const open = typeof force === "boolean" ? force : el.debugBody.hidden;
    el.debugBody.hidden = !open;
    el.debugToggle.setAttribute("aria-expanded", String(open));
    if (open) {
      debug.unseen = 0;
      el.debugBadge.hidden = true;
      el.debugBadge.classList.remove("debug-badge--alert");
      el.debugLog.scrollTop = el.debugLog.scrollHeight;
    }
  }

  async function copyDebug() {
    const text = debug.entries
      .map((entry) => `${entry.time.toLocaleTimeString("pt-BR", { hour12: false })} ${entry.level.toUpperCase()} ${entry.message}`)
      .join("\n");
    if (!text) {
      toast("Nada para copiar.", "info");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast("Log copiado.", "success");
    } catch {
      toast("Não foi possível copiar o log.", "error");
    }
  }

  function clearDebug() {
    debug.entries = [];
    el.debugLog.innerHTML = '<span class="debug-log__empty">Nenhum evento registrado ainda.</span>';
  }

  function stopMetricsRefresh() {
    window.clearInterval(state.metricsTimer);
    state.metricsTimer = null;
  }

  function startMetricsRefresh() {
    stopMetricsRefresh();
    state.metricsTimer = window.setInterval(loadMetrics, 10000);
  }

  function renderRouteMetrics(routes) {
    el.metricsRoutes.textContent = "";
    if (!routes.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 3;
      cell.className = "metrics-empty";
      cell.textContent = "Nenhuma requisição registrada.";
      row.appendChild(cell);
      el.metricsRoutes.appendChild(row);
      return;
    }
    routes.slice(0, 8).forEach((route) => {
      const row = document.createElement("tr");
      const name = document.createElement("td");
      const calls = document.createElement("td");
      const average = document.createElement("td");
      name.textContent = route.route;
      calls.textContent = String(route.requests);
      average.textContent = formatDuration(route.average_response_ms);
      row.append(name, calls, average);
      el.metricsRoutes.appendChild(row);
    });
  }

  async function loadMetrics() {
    if (el.refreshMetricsBtn.disabled) return;
    el.refreshMetricsBtn.disabled = true;
    el.metricsGrid.setAttribute("aria-busy", "true");
    try {
      const response = await fetch("/api/metrics", { cache: "no-store" });
      if (!response.ok) throw new Error("Não foi possível carregar as métricas.");
      const data = await response.json();
      el.metricAverage.textContent = formatDuration(data.average_response_ms);
      el.metricP95.textContent = formatDuration(data.p95_response_ms);
      el.metricSuccess.textContent = `${data.success_rate.toFixed(1)}%`;
      el.metricSuccess.classList.toggle("metric-card__value--danger", data.success_rate < 95);
      el.metricErrors.textContent = data.errors === 1 ? "1 erro registrado" : `${data.errors} erros registrados`;
      el.metricRequests.textContent = data.requests.toLocaleString("pt-BR");
      el.metricImages.textContent = data.image_generations.toLocaleString("pt-BR");
      el.metricUptime.textContent = `Ativa há ${formatUptime(data.uptime_seconds)}`;
      el.metricUpdated.textContent = `Atualizado às ${new Date(data.generated_at * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
      const tokens = data.tokens || { input: 0, output: 0, total: 0 };
      const cost = data.cost || { total: 0, image: 0, per_image: 0 };
      el.metricTokens.textContent = formatTokens(tokens.total);
      el.metricTokensBreak.textContent = `${formatTokens(tokens.input)} entrada · ${formatTokens(tokens.output)} saída`;
      el.metricCost.textContent = cost.complete === false
        ? `${formatUSD(cost.total)} parcial`
        : formatUSD(cost.total);
      el.metricCostPerImage.textContent = cost.complete === false ? "—" : formatUSD(cost.per_image);
      renderRouteMetrics(data.routes || []);
      renderDashboard(data);
    } catch (error) {
      toast(error.message, "error");
      el.metricUpdated.textContent = "Falha na atualização";
    } finally {
      el.refreshMetricsBtn.disabled = false;
      el.metricsGrid.setAttribute("aria-busy", "false");
    }
  }

  /* ------------------------------------------------------------ dashboard */

  function switchView(name) {
    const isDashboard = name === "dashboard";
    body.dataset.view = isDashboard ? "dashboard" : "app";
    el.navApp.classList.toggle("is-active", !isDashboard);
    el.navDashboard.classList.toggle("is-active", isDashboard);
    el.navApp.setAttribute("aria-selected", String(!isDashboard));
    el.navDashboard.setAttribute("aria-selected", String(isDashboard));
    if (isDashboard) refreshDashboard();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function refreshDashboard() {
    await loadMetrics();
  }

  function switchDashboardMode(mode) {
    const showExecutions = mode === "execution";
    el.executionResults.hidden = !showExecutions;
    document.querySelectorAll('[data-dashboard-panel="consolidated"]').forEach((node) => {
      node.hidden = showExecutions;
    });
    Array.from(el.dashboardMode.children).forEach((node) => {
      const active = node.dataset.value === mode;
      node.classList.toggle("is-active", active);
      node.setAttribute("aria-checked", String(active));
    });
  }

  function executionKey(item) {
    return item.execution_id || `${item.type}:${item.id}:${item.at}`;
  }

  function syncExecutionSelection(items) {
    const available = new Set(items.map(executionKey));
    if (state.dashboardSelectAll) {
      state.selectedExecutionIds = available;
      return;
    }
    state.selectedExecutionIds = new Set(
      Array.from(state.selectedExecutionIds).filter((id) => available.has(id))
    );
  }

  function selectedExecutions(items) {
    return items.filter((item) => state.selectedExecutionIds.has(executionKey(item)));
  }

  function executionPercentile(values, percentile) {
    if (!values.length) return 0;
    const ordered = [...values].sort((left, right) => left - right);
    return ordered[Math.max(0, Math.ceil(ordered.length * percentile) - 1)];
  }

  function consolidateExecutions(base, items) {
    const images = items;
    const pricedImages = images.filter((item) => item.cost_configured !== false);
    const sum = (values) => values.reduce((total, value) => total + Number(value || 0), 0);
    const imageDurations = images.map((item) => Number(item.elapsed_ms || 0));
    const inputText = sum(images.map((item) => item.input_text_tokens));
    const inputImage = sum(images.map((item) => item.input_image_tokens));
    const outputImage = sum(images.map((item) => item.output_image_tokens));
    const inputMegapixels = sum(images.map((item) => item.input_megapixels));
    const outputMegapixels = sum(images.map((item) => item.output_megapixels));
    const imageCost = sum(images.map((item) => item.cost));
    const unpricedImages = images.length - pricedImages.length;

    return {
      ...base,
      requests: items.length,
      errors: 0,
      success_rate: 100,
      average_response_ms: images.length ? sum(imageDurations) / images.length : 0,
      p95_response_ms: executionPercentile(imageDurations, 0.95),
      image_generations: images.length,
      image_average_ms: images.length ? sum(imageDurations) / images.length : 0,
      image_p95_ms: executionPercentile(imageDurations, 0.95),
      megapixels: {
        input: inputMegapixels,
        output: outputMegapixels,
        total: inputMegapixels + outputMegapixels,
      },
      tokens: {
        input: inputText + inputImage,
        input_text: inputText,
        input_image: inputImage,
        output: outputImage,
        output_image: outputImage,
        total: inputText + inputImage + outputImage,
      },
      cost: {
        image: imageCost,
        total: imageCost,
        per_image: pricedImages.length ? imageCost / pricedImages.length : 0,
        complete: unpricedImages === 0,
        unpriced_images: unpricedImages,
        currency: "USD",
      },
      recent: items,
    };
  }

  function simulatorNumber(element) {
    const value = Number(element.value);
    return Number.isFinite(value) && value >= 0 ? value : 0;
  }

  function saveSimulatorAssumptions() {
    const values = {
      monthlyAiSessions: el.scaleVolume.value,
      looksPerSession: el.scaleLooksPerSession.value,
      cacheEnabled: el.scaleCacheEnabled.checked,
      exchangeRate: el.scaleExchangeRate.value,
      imageCost: el.scaleImageCost.value,
      baselineCost: el.scaleBaselineCost.value,
      lunaInputTokens: el.lunaInputTokens.value,
      lunaOutputTokens: el.lunaOutputTokens.value,
      lunaCachedShare: el.lunaCachedShare.value,
      lunaCacheWriteTokens: el.lunaCacheWriteTokens.value,
      lunaCurrentCached: el.lunaCurrentCached.value,
      lunaCurrentUncached: el.lunaCurrentUncached.value,
    };
    localStorage.setItem(SIMULATOR_STORAGE_KEY, JSON.stringify(values));
  }

  function restoreSimulatorAssumptions() {
    try {
      const values = JSON.parse(localStorage.getItem(SIMULATOR_STORAGE_KEY) || "null");
      if (!values) return;
      if (values.monthlyAiSessions !== undefined) el.scaleVolume.value = values.monthlyAiSessions;
      if (values.looksPerSession !== undefined) el.scaleLooksPerSession.value = values.looksPerSession;
      if (typeof values.cacheEnabled === "boolean") el.scaleCacheEnabled.checked = values.cacheEnabled;
      if (values.exchangeRate !== undefined) el.scaleExchangeRate.value = values.exchangeRate;
      if (values.imageCost !== undefined) el.scaleImageCost.value = values.imageCost;
      if (values.baselineCost !== undefined) el.scaleBaselineCost.value = values.baselineCost;
      if (values.lunaInputTokens !== undefined) el.lunaInputTokens.value = values.lunaInputTokens;
      if (values.lunaOutputTokens !== undefined) el.lunaOutputTokens.value = values.lunaOutputTokens;
      if (values.lunaCachedShare !== undefined) el.lunaCachedShare.value = values.lunaCachedShare;
      if (values.lunaCacheWriteTokens !== undefined) el.lunaCacheWriteTokens.value = values.lunaCacheWriteTokens;
      if (values.lunaCurrentCached !== undefined) el.lunaCurrentCached.value = values.lunaCurrentCached;
      if (values.lunaCurrentUncached !== undefined) el.lunaCurrentUncached.value = values.lunaCurrentUncached;
    } catch {
      localStorage.removeItem(SIMULATOR_STORAGE_KEY);
    }
  }

  function renderScaleProjection(data) {
    const cost = data?.cost || { per_image: 0 };
    const looksPerSession = simulatorNumber(el.scaleLooksPerSession);
    const exchangeRate = simulatorNumber(el.scaleExchangeRate);
    const measuredImageCost = cost.complete === false
      ? 0
      : Number(cost.per_image || 0) * exchangeRate;
    const imageOverride = simulatorNumber(el.scaleImageCost);
    const imageUnitCost = imageOverride || measuredImageCost;
    const baselineUnitCost = simulatorNumber(el.scaleBaselineCost);

    const coveredSessions = simulatorNumber(el.scaleVolume);
    renderLunaProjection(coveredSessions, exchangeRate);
    const requestedLooks = coveredSessions * looksPerSession;
    el.scaleMonthlyLooks.value = formatCount(Math.round(requestedLooks));
    const cacheReduction = el.scaleCacheEnabled.checked ? 0.2 : 0;
    const billableLooks = requestedLooks * (1 - cacheReduction);
    const hasRequiredCosts = imageUnitCost > 0;

    el.scaleCoverage.textContent = formatCount(Math.round(coveredSessions));
    el.scaleAdditionalCoverage.textContent = formatCount(
      Math.max(0, Math.round(coveredSessions - DEFAULT_MONTHLY_AI_SESSIONS))
    );

    el.scaleImageCost.placeholder = measuredImageCost > 0
      ? `Medido: ${formatBRL(measuredImageCost)}`
      : "Telemetria do piloto";

    if (!hasRequiredCosts) {
      el.scaleMonthlyCost.textContent = "—";
      el.scaleAnnualCost.textContent = "—";
      el.scaleCostPerJourney.textContent = "Informe os custos unitários ou conclua as gerações do piloto";
      el.scaleMonthlySavings.textContent = "—";
      el.scaleAnnualSavings.textContent = "—";
      el.scaleSavingsRate.textContent = "Aguardando custos unitários";
      el.scaleSourceNote.textContent = "A projeção financeira será calculada após a telemetria registrar o custo de imagem, ou após o preenchimento do valor contratual.";
      return;
    }

    const monthlyCost = billableLooks * imageUnitCost;
    const costPerJourney = coveredSessions > 0 ? monthlyCost / coveredSessions : 0;
    el.scaleMonthlyCost.textContent = formatBRL(monthlyCost);
    el.scaleAnnualCost.textContent = formatBRL(monthlyCost * 12);
    el.scaleCostPerJourney.textContent = `${formatBRL(costPerJourney)} por jornada participante`;

    const sources = [];
    sources.push(imageOverride ? "imagem: valor informado" : "imagem: telemetria do piloto");
    el.scaleSourceNote.textContent = `Base de cálculo: ${sources.join("; ")}. O cache considera 20% de reutilização quando ativado.`;

    if (baselineUnitCost <= 0) {
      el.scaleMonthlySavings.textContent = "—";
      el.scaleAnnualSavings.textContent = "—";
      el.scaleSavingsRate.textContent = "Informe o baseline validado";
      el.scaleMonthlySavings.classList.remove("is-negative");
      return;
    }

    const baselineMonthlyCost = requestedLooks * baselineUnitCost;
    const monthlySavings = baselineMonthlyCost - monthlyCost;
    const savingsRate = baselineMonthlyCost > 0 ? (monthlySavings / baselineMonthlyCost) * 100 : 0;
    el.scaleMonthlySavings.textContent = formatBRL(monthlySavings);
    el.scaleAnnualSavings.textContent = formatBRL(monthlySavings * 12);
    el.scaleSavingsRate.textContent = monthlySavings >= 0
      ? `${savingsRate.toFixed(1).replace(".", ",")}% abaixo do baseline`
      : `${Math.abs(savingsRate).toFixed(1).replace(".", ",")}% acima do baseline`;
    el.scaleMonthlySavings.classList.toggle("is-negative", monthlySavings < 0);
  }

  function renderLunaProjection(monthlySessions, exchangeRate) {
    const inputTokens = simulatorNumber(el.lunaInputTokens);
    const outputTokens = simulatorNumber(el.lunaOutputTokens);
    const cachedShare = Math.min(100, simulatorNumber(el.lunaCachedShare)) / 100;
    const cacheWriteTokens = simulatorNumber(el.lunaCacheWriteTokens);
    const currentCachedText = simulatorNumber(el.lunaCurrentCached);
    const currentUncachedText = simulatorNumber(el.lunaCurrentUncached);

    const uncachedInputUsd = inputTokens / 1_000_000 * LUNA_INPUT_PRICE_PER_1M;
    const cachedInputUsd = (
      inputTokens * (1 - cachedShare) / 1_000_000 * LUNA_INPUT_PRICE_PER_1M
      + inputTokens * cachedShare / 1_000_000 * LUNA_CACHED_INPUT_PRICE_PER_1M
    );
    const outputUsd = outputTokens / 1_000_000 * LUNA_OUTPUT_PRICE_PER_1M;
    const cacheWriteMonthly = cacheWriteTokens / 1_000_000
      * LUNA_CACHE_WRITE_PRICE_PER_1M
      * exchangeRate;
    const lunaUncachedText = (uncachedInputUsd + outputUsd) * exchangeRate;
    const lunaCachedText = (cachedInputUsd + outputUsd) * exchangeRate
      + (monthlySessions > 0 ? cacheWriteMonthly / monthlySessions : 0);

    const currentCachedMonthly = currentCachedText * monthlySessions;
    const currentUncachedMonthly = currentUncachedText * monthlySessions;
    const lunaCachedMonthly = lunaCachedText * monthlySessions;
    const lunaUncachedMonthly = lunaUncachedText * monthlySessions;
    const cachedSavings = currentCachedMonthly - lunaCachedMonthly;
    const uncachedSavings = currentUncachedMonthly - lunaUncachedMonthly;

    el.lunaMonthlySessions.value = formatCount(Math.round(monthlySessions));
    el.lunaCurrentCachedPerSession.textContent = formatBRL(currentCachedText);
    el.lunaCurrentCachedMonthly.textContent = formatBRL(currentCachedMonthly);
    el.lunaCachedPerSession.textContent = formatBRL(lunaCachedText);
    el.lunaCachedMonthly.textContent = formatBRL(lunaCachedMonthly);
    el.lunaCurrentUncachedPerSession.textContent = formatBRL(currentUncachedText);
    el.lunaCurrentUncachedMonthly.textContent = formatBRL(currentUncachedMonthly);
    el.lunaUncachedPerSession.textContent = formatBRL(lunaUncachedText);
    el.lunaUncachedMonthly.textContent = formatBRL(lunaUncachedMonthly);
    el.lunaCachedSavings.textContent = formatBRL(cachedSavings);
    el.lunaUncachedSavings.textContent = formatBRL(uncachedSavings);
    el.lunaCachedSavings.classList.toggle("is-negative", cachedSavings < 0);
    el.lunaUncachedSavings.classList.toggle("is-negative", uncachedSavings < 0);
    el.lunaSourceNote.textContent = `Cache: ${(cachedShare * 100).toFixed(0)}% da entrada; escrita mensal: ${formatTokens(cacheWriteTokens)} tokens. Saída: ${formatTokens(outputTokens)} tokens por sessão.`;
  }

  function renderDashboard(data) {
    if (!el.dashGrid) return;
    state.lastMetrics = data;
    const executions = (data.executions || []).filter((item) => item.type === "image");
    syncExecutionSelection(executions);
    renderExecutions(executions);
    data = consolidateExecutions(data, selectedExecutions(executions));
    const tokens = data.tokens || { input: 0, output: 0, total: 0 };
    const megapixels = data.megapixels || { input: 0, output: 0, total: 0 };
    const cost = data.cost || { total: 0, image: 0, per_image: 0 };
    const exchangeRate = simulatorNumber(el.scaleExchangeRate);
    const costPerLookBrl = cost.per_image * exchangeRate;

    el.dashLooks.textContent = formatCount(data.image_generations);
    el.dashAvgTime.textContent = data.image_average_ms ? formatDuration(data.image_average_ms) : "—";
    el.dashP95Time.textContent = data.image_p95_ms ? formatDuration(data.image_p95_ms) : "—";
    el.dashSuccess.textContent = `${data.success_rate.toFixed(1)}%`;
    el.dashSuccess.classList.toggle("dash-card__value--warn", data.success_rate < 95);
    el.dashErrors.textContent = data.errors ? `${data.errors} falha(s) registrada(s)` : "sem falhas registradas";
    el.dashTokens.textContent = formatTokens(tokens.total);
    el.dashTokensPerLook.textContent = data.image_generations
      ? formatTokens(tokens.total / data.image_generations)
      : "—";
    el.dashTokensBreak.textContent =
      `${formatTokens(tokens.input_text || 0)} tokens de texto, ` +
      `${formatTokens(tokens.input_image || 0)} de imagem na entrada e ` +
      `${formatTokens(tokens.output_image || tokens.output || 0)} de imagem na saída.`;
    el.dashCostTotal.textContent = cost.complete === false
      ? `${formatUSD(cost.total)} parcial`
      : formatUSD(cost.total);
    el.dashCostPer.textContent = cost.complete !== false && cost.per_image > 0
      ? formatBRL(costPerLookBrl)
      : "—";
    el.dashObservedAt.textContent = `Atualizado às ${new Date(data.generated_at * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
    el.dashExecutiveSummary.textContent = data.image_generations
      ? `${formatCount(data.image_generations)} look(s) concluído(s), com custo médio de ${formatBRL(costPerLookBrl)} e tempo médio de ${formatDuration(data.image_average_ms)} por resultado.`
      : "Gere um look para consolidar os resultados desta demonstração.";

    el.costImage.textContent = formatUSD(cost.image);
  el.dashInputMegapixels.textContent = `${Number(megapixels.input || 0).toFixed(3).replace(".", ",")} MP`;
  el.dashOutputMegapixels.textContent = `${Number(megapixels.output || 0).toFixed(3).replace(".", ",")} MP`;

    renderScaleProjection(data);
    renderRecent(data.recent || []);
  }

  function renderExecutions(items) {
    el.executionRows.textContent = "";
    const selectedCount = state.selectedExecutionIds.size;
    el.executionCount.textContent = !items.length
      ? "0 execuções"
      : state.dashboardSelectAll
      ? items.length === 1 ? "1 execução · selecionada" : `${formatCount(items.length)} execuções · todas selecionadas`
      : `${formatCount(selectedCount)} de ${formatCount(items.length)} selecionadas`;
    el.selectAllExecutions.setAttribute("aria-pressed", String(state.dashboardSelectAll));
    el.selectAllExecutions.classList.toggle("is-active", state.dashboardSelectAll);
    if (!items.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 11;
      cell.className = "execution-empty";
      cell.textContent = "Nenhuma execução de imagem registrada.";
      row.appendChild(cell);
      el.executionRows.appendChild(row);
      return;
    }

    items.forEach((item) => {
      const row = document.createElement("tr");
      const key = executionKey(item);
      const selectCell = document.createElement("td");
      selectCell.className = "execution-table__select";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.selectedExecutionIds.has(key);
      checkbox.setAttribute("aria-label", `Selecionar execução ${String(item.id || "").slice(0, 8)}`);
      checkbox.addEventListener("change", () => {
        state.dashboardSelectAll = false;
        if (checkbox.checked) state.selectedExecutionIds.add(key);
        else state.selectedExecutionIds.delete(key);
        if (state.selectedExecutionIds.size === items.length) state.dashboardSelectAll = true;
        if (state.lastMetrics) renderDashboard(state.lastMetrics);
      });
      selectCell.appendChild(checkbox);
      row.appendChild(selectCell);
      const values = [
        new Date(item.at * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        item.model || "—",
        formatDuration(item.elapsed_ms || 0),
        item.input_text_tokens ? formatTokens(item.input_text_tokens) : "—",
        item.input_image_tokens ? formatTokens(item.input_image_tokens) : "—",
        item.output_image_tokens ? formatTokens(item.output_image_tokens) : "—",
        item.input_megapixels ? `${Number(item.input_megapixels).toFixed(3).replace(".", ",")} MP` : "—",
        item.output_megapixels ? `${Number(item.output_megapixels).toFixed(3).replace(".", ",")} MP` : "—",
        item.cost_configured === false ? "Não configurado" : formatUSD(item.cost || 0),
        String(item.id || "").slice(0, 8),
      ];
      values.forEach((value, index) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        if (index === 8) cell.className = "execution-table__cost";
        if (index === 9) cell.className = "execution-table__id";
        row.appendChild(cell);
      });
      el.executionRows.appendChild(row);
    });
  }

  function renderRecent(items) {
    el.recentList.textContent = "";
    if (!items.length) {
      const li = document.createElement("li");
      li.className = "recent-empty";
      li.textContent = "Nenhuma geração registrada até o momento.";
      el.recentList.appendChild(li);
      return;
    }
    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "recent-item";
      const detail = `${item.model || "GPT Image 2"} · ${formatTokens(item.tokens)} tokens`;
      const time = new Date(item.at * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      li.innerHTML =
        `<span class="recent-item__kind recent-item__kind--image">Look</span>` +
        `<span class="recent-item__id">${String(item.id).slice(0, 8)}</span>` +
        `<span class="recent-item__meta">${detail}</span>` +
        `<span class="recent-item__cost">${formatUSD(item.cost)}</span>` +
        `<span class="recent-item__time">${time}</span>`;
      el.recentList.appendChild(li);
    });
  }

  /* -------------------------------------------------------------- galeria */

  function addToGallery(item) {
    state.gallery.unshift(item);
    renderGallery();
  }

  function renderGallery() {
    el.galleryStrip.textContent = "";
    el.galleryHint.textContent = state.gallery.length
      ? `${state.gallery.length} look(s) nesta sessão`
      : "Os looks gerados nesta sessão aparecem aqui.";

    state.gallery.forEach((item) => {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "gallery__item";
      button.dataset.imageId = item.imageId;
      button.setAttribute("aria-label", `Abrir look ${item.imageId.slice(0, 8)}`);

      const img = document.createElement("img");
      img.src = item.imageUrl;
      img.alt = "";
      button.appendChild(img);

      button.addEventListener("click", () => {
        applyResult(item);
      });

      li.appendChild(button);
      el.galleryStrip.appendChild(li);
    });
    highlightGallery();
  }

  function highlightGallery() {
    Array.from(el.galleryStrip.querySelectorAll(".gallery__item")).forEach((node) => {
      node.classList.toggle("is-active", node.dataset.imageId === state.current?.imageId);
    });
  }

  /* ------------------------------------------------------------------ init */

  function init() {
    initTheme();
    initCompare();

    debug.log = el.debugLog;
    debug.badge = el.debugBadge;
    debug.body = el.debugBody;
    debug.autoscroll = el.debugAutoscroll;
    debug.entries.forEach(renderDebugEntry);
    debugLog("info", `Interface pronta (v${body.dataset.version || ""}).`);

    bindDropzone(el.personDropzone, el.personInput, setPerson);
    bindDropzone(el.garmentDropzone, el.garmentInput, addGarments);

    el.personRemove.addEventListener("click", (event) => {
      event.stopPropagation();
      clearPerson();
    });

    document.addEventListener("paste", (event) => {
      const files = Array.from(event.clipboardData?.files || []).filter((file) =>
        file.type.startsWith("image/")
      );
      if (!files.length) return;
      event.preventDefault();
      if (!state.person) {
        setPerson(files);
        toast("Foto de corpo inteiro colada.", "success", 3000);
      } else {
        addGarments(files);
        toast("Peça(s) colada(s).", "success", 3000);
      }
    });

    el.generateBtn.addEventListener("click", generateLook);
    el.regenerateBtn.addEventListener("click", generateLook);

    el.metricsToggle.addEventListener("click", () => toggleMetrics());
    el.refreshMetricsBtn.addEventListener("click", loadMetrics);

    el.debugToggle.addEventListener("click", () => toggleDebug());
    el.debugCopyBtn.addEventListener("click", copyDebug);
    el.debugClearBtn.addEventListener("click", clearDebug);

    el.dashboardRefreshBtn.addEventListener("click", refreshDashboard);
    el.selectAllExecutions.addEventListener("click", () => {
      state.dashboardSelectAll = true;
      if (state.lastMetrics) renderDashboard(state.lastMetrics);
    });
    el.dashboardMode.addEventListener("click", (event) => {
      const target = event.target.closest(".segmented__item");
      if (target?.dataset.value) switchDashboardMode(target.dataset.value);
    });

    restoreSimulatorAssumptions();
    el.scaleControls.addEventListener("submit", (event) => event.preventDefault());
    el.scaleControls.addEventListener("input", () => {
      saveSimulatorAssumptions();
      if (state.lastMetrics) renderDashboard(state.lastMetrics);
    });
    el.scaleControls.addEventListener("change", () => {
      saveSimulatorAssumptions();
      if (state.lastMetrics) renderDashboard(state.lastMetrics);
    });
    el.lunaControls.addEventListener("submit", (event) => event.preventDefault());
    el.lunaControls.addEventListener("input", () => {
      saveSimulatorAssumptions();
      if (state.lastMetrics) renderDashboard(state.lastMetrics);
    });
    el.lunaControls.addEventListener("change", () => {
      saveSimulatorAssumptions();
      if (state.lastMetrics) renderDashboard(state.lastMetrics);
    });

    el.navApp.addEventListener("click", () => switchView("app"));
    el.navDashboard.addEventListener("click", () => switchView("dashboard"));

    window.addEventListener("beforeunload", () => {
      stopMetricsRefresh();
    });
    renderGallery();
    refreshDashboard();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
