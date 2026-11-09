// VoiceDesk AI — Executive Conversational Voice Platform v5.0
// Unified Live Voice & Chat Console, Strict Session Termination, Authentic Pakistani Urdu Phonetics,
// and Multimodal Physical Transaction Documents.

document.addEventListener("DOMContentLoaded", () => {
  // =========================================================================
  // DOM Elements
  // =========================================================================

  // Global Navigation Tabs
  const tabButtons = document.querySelectorAll(".nav-tabs .tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");

  // Sidebar Controls
  const studioSidebar = document.getElementById("studio-sidebar");
  const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");
  const btnMobileSidebarToggle = document.getElementById("btn-mobile-sidebar-toggle");
  const agentConfigForm = document.getElementById("agent-config-form");
  const inputAgentName = document.getElementById("agent-name");
  const inputAgentRole = document.getElementById("agent-role");
  const toneRadioPills = document.querySelectorAll(".radio-pill");
  const voiceSegButtons = document.querySelectorAll(".vseg-btn");
  const subpanelPreset = document.getElementById("subpanel-preset");
  const subpanelClone = document.getElementById("subpanel-clone");
  const voiceCards = document.querySelectorAll(".voice-card");
  const sidebarVoiceSpeed = document.getElementById("sidebar-voice-speed");
  const sidebarSpeedVal = document.getElementById("sidebar-speed-val");

  // Sidebar Voice Recording (Clone mode)
  const btnSidebarStartRecord = document.getElementById("btn-sidebar-start-record");
  const btnSidebarStopRecord = document.getElementById("btn-sidebar-stop-record");
  const btnSidebarRerecord = document.getElementById("btn-sidebar-rerecord");
  const sidebarRecordTimer = document.getElementById("sidebar-record-timer");
  const sidebarWaveformCanvas = document.getElementById("sidebar-waveform-canvas");
  const sidebarVoicePreview = document.getElementById("sidebar-voice-preview");
  const sidebarPreviewAudio = document.getElementById("sidebar-preview-audio");

  // Sidebar Business Inputs
  const inputBizName = document.getElementById("biz-name");
  const inputBizCategory = document.getElementById("biz-category");
  const inputBizDescription = document.getElementById("biz-description");
  const inputBizLocation = document.getElementById("biz-location");
  const inputBizHours = document.getElementById("biz-hours");
  const sidebarServicesList = document.getElementById("sidebar-services-list");
  const btnSidebarAddService = document.getElementById("btn-sidebar-add-service");
  const inputFallbackResponse = document.getElementById("fallback-response");
  const btnUpdateAgent = document.getElementById("btn-update-agent");

  // Right Console Elements
  const consoleAgentName = document.getElementById("console-agent-name");
  const consoleVoiceBadge = document.getElementById("console-voice-badge");
  const consoleAgentTitle = document.getElementById("console-agent-title");
  const consoleBizName = document.getElementById("console-biz-name");
  const agentAvatarInitials = document.getElementById("agent-avatar-initials");
  const avatarLiveIndicator = document.getElementById("avatar-live-indicator");
  const callStatePill = document.getElementById("call-state-pill");
  const callStateLabel = document.getElementById("call-state-label");

  // Chat Viewport & Welcome
  const chatViewport = document.getElementById("chat-viewport");
  const welcomeSpeakerLabel = document.getElementById("welcome-speaker-label");
  const welcomeTextDisplay = document.getElementById("welcome-text-display");
  const btnPlayWelcome = document.getElementById("btn-play-welcome");

  // Suggestion Chips
  const chipsList = document.getElementById("chips-list");

  // Dock Telephony Controls
  const btnMainCallAction = document.getElementById("btn-main-call-action");
  const callBtnText = document.getElementById("call-btn-text");
  const btnDockMic = document.getElementById("btn-dock-mic");
  const btnDockInterrupt = document.getElementById("btn-dock-interrupt");
  const acousticWaveBars = document.getElementById("acoustic-wave-bars");
  const dockAcousticLabel = document.getElementById("dock-acoustic-label");
  const textChatForm = document.getElementById("text-chat-form");
  const textChatInput = document.getElementById("text-chat-input");

  // Tab 2: Receipts & OCR
  const btnDownloadReceiptPng = document.getElementById("btn-download-receipt-png");
  const btnPrintReceipt = document.getElementById("btn-print-receipt");
  const receiptPaperImg = document.getElementById("receipt-paper-img");
  const ocrDropzone = document.getElementById("ocr-dropzone");
  const ocrFileInput = document.getElementById("ocr-file-input");
  const btnBrowseOcr = document.getElementById("btn-browse-ocr");
  const ocrStatusBar = document.getElementById("ocr-status-bar");
  const ocrStatusText = document.getElementById("ocr-status-text");
  const ocrJsonDisplay = document.getElementById("ocr-json-display");

  // =========================================================================
  // State Machine
  // =========================================================================
  let currentSessionId = null;
  let isCallActive = false;
  let isMicMuted = false;
  let isAiSpeaking = false;
  let ignoreSpeechUntil = 0;
  let lastSpokenText = "";
  let lastSpokenTime = 0;

  // Active Profile Data
  let activeVoiceMode = "preset"; // "preset" or "clone"
  let recordedVoiceBlob = null;
  let welcomeAudioB64 = "";

  // Web Audio API State
  let audioContext = null;
  let currentSourceNode = null;
  let activeFetchController = null;

  // Telephony & Recognition
  let speechRecognizer = null;
  let ws = null;
  let callTimerInterval = null;
  let callSecondsElapsed = 0;

  // Recording Stream & Canvas
  let recorderMediaStream = null;
  let mediaRecorder = null;
  let recorderTimer = null;
  let secondsRecorded = 0;
  let waveformAnimId = null;

  // Services Seed
  let currentServices = [
    { name: "Teeth Scaling & Deep Polishing", price_pkr: 4000 },
    { name: "Laser Teeth Whitening", price_pkr: 12000 },
    { name: "General Dental Consultation", price_pkr: 1500 }
  ];

  // =========================================================================
  // 1. Web Audio API Engine
  // =========================================================================

  function getAudioContext() {
    if (!audioContext) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      audioContext = new AudioCtx();
    }
    if (audioContext.state === "suspended") {
      audioContext.resume();
    }
    return audioContext;
  }

  async function playAudioBuffer(base64Mp3) {
    if (!base64Mp3) return;

    // Strict termination guard: do not play audio if user hung up
    if (!isCallActive) {
      console.log("Audio play ignored because call is not active.");
      return;
    }

    const ctx = getAudioContext();
    stopAudioBufferPlayback(false);

    try {
      const binaryString = atob(base64Mp3);
      const len = binaryString.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      const audioBuffer = await ctx.decodeAudioData(bytes.buffer.slice(0));

      // Re-verify call is still active after async decode
      if (!isCallActive) return;

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);

      currentSourceNode = source;
      isAiSpeaking = true;

      setDockAcousticState("speaking", `${inputAgentName.value || "Agent"} is speaking...`);

      // Temporarily pause speech recognition so mic doesn't capture speaker output
      if (speechRecognizer) {
        try { speechRecognizer.abort(); } catch (e) {}
      }

      source.onended = () => {
        if (currentSourceNode === source) {
          currentSourceNode = null;
        }
        isAiSpeaking = false;

        if (isCallActive) {
          setDockAcousticState("listening", "Listening to you...");
          ignoreSpeechUntil = Date.now() + 400;
          setTimeout(() => {
            if (isCallActive && !isMicMuted && !isAiSpeaking && speechRecognizer) {
              try { speechRecognizer.start(); } catch (e) {}
            }
          }, 300);
        } else {
          setDockAcousticState("idle", "Call ended");
        }
      };

      source.start(0);
    } catch (err) {
      console.error("Audio playback error:", err);
      isAiSpeaking = false;
      if (isCallActive) {
        setDockAcousticState("listening", "Listening to you...");
        if (!isMicMuted && speechRecognizer) {
          try { speechRecognizer.start(); } catch (e) {}
        }
      }
    }
  }

  function stopAudioBufferPlayback(notifyServer = true) {
    if (currentSourceNode) {
      try {
        currentSourceNode.stop();
        currentSourceNode.disconnect();
      } catch (e) {}
      currentSourceNode = null;
    }
    isAiSpeaking = false;

    if (isCallActive) {
      setDockAcousticState("listening", "Listening to you...");
    }

    if (notifyServer && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "interruption" }));
    }
  }

  function setDockAcousticState(mode, text) {
    if (dockAcousticLabel) dockAcousticLabel.textContent = text;

    if (mode === "speaking") {
      acousticWaveBars?.classList.add("active");
    } else if (mode === "thinking") {
      acousticWaveBars?.classList.remove("active");
    } else if (mode === "listening") {
      acousticWaveBars?.classList.remove("active");
    } else {
      acousticWaveBars?.classList.remove("active");
    }
  }

  // =========================================================================
  // 2. Global Tab Navigation
  // =========================================================================

  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetTabId = btn.getAttribute("data-tab");
      switchGlobalTab(targetTabId);
    });
  });

  function switchGlobalTab(tabId) {
    tabButtons.forEach(b => {
      const isActive = b.getAttribute("data-tab") === tabId;
      b.classList.toggle("active", isActive);
      b.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    tabPanes.forEach(p => {
      p.classList.toggle("active", p.id === tabId);
    });
  }

  // Mobile sidebar toggle
  if (btnMobileSidebarToggle && studioSidebar) {
    btnMobileSidebarToggle.addEventListener("click", () => {
      studioSidebar.classList.toggle("mobile-open");
    });
  }
  if (btnToggleSidebar && studioSidebar) {
    btnToggleSidebar.addEventListener("click", () => {
      studioSidebar.classList.remove("mobile-open");
    });
  }

  // =========================================================================
  // 3. Sidebar Studio: Persona, Voices & Dynamic Services
  // =========================================================================

  // Tone Selection
  toneRadioPills.forEach(pill => {
    pill.addEventListener("click", () => {
      toneRadioPills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      const radio = pill.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // Voice Mode Switching (Preset vs Clone)
  voiceSegButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      voiceSegButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeVoiceMode = btn.getAttribute("data-vmode");

      if (activeVoiceMode === "preset") {
        subpanelPreset.style.display = "block";
        subpanelClone.style.display = "none";
      } else {
        subpanelClone.style.display = "block";
        subpanelPreset.style.display = "none";
      }
    });
  });

  // Voice Tile Cards
  voiceCards.forEach(card => {
    card.addEventListener("click", () => {
      voiceCards.forEach(c => c.classList.remove("active"));
      card.classList.add("active");
      const radio = card.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
      updateConsoleVoiceBadge();
    });
  });

  function updateConsoleVoiceBadge() {
    if (activeVoiceMode === "clone") {
      consoleVoiceBadge.textContent = "★ Zero-Shot Voice Clone";
    } else {
      const selected = document.querySelector('input[name="preset-voice"]:checked')?.value || "ur-PK-UzmaNeural";
      if (selected.includes("Uzma")) {
        consoleVoiceBadge.textContent = "Studio Uzma (Lahori)";
      } else if (selected.includes("Asad")) {
        consoleVoiceBadge.textContent = "Studio Asad (Islamabad)";
      } else if (selected.includes("aiza")) {
        consoleVoiceBadge.textContent = "Studio Aiza (Lahori • Fish Audio)";
      } else {
        consoleVoiceBadge.textContent = "Studio Pakistani Neural";
      }
    }
  }

  // Voice Speed Slider
  if (sidebarVoiceSpeed && sidebarSpeedVal) {
    sidebarVoiceSpeed.addEventListener("input", () => {
      sidebarSpeedVal.textContent = `${parseFloat(sidebarVoiceSpeed.value).toFixed(2)}x`;
    });
  }

  // Dynamic Services Rows
  function renderSidebarServices() {
    sidebarServicesList.innerHTML = "";
    currentServices.forEach((svc, index) => {
      const row = document.createElement("div");
      row.className = "sidebar-service-row";
      row.innerHTML = `
        <input type="text" class="svc-name" value="${escapeHtml(svc.name)}" placeholder="Item / Service">
        <input type="number" class="svc-price" value="${svc.price_pkr}" placeholder="PKR">
        <button type="button" class="btn-del-row" data-idx="${index}" title="Remove">&times;</button>
      `;
      sidebarServicesList.appendChild(row);
    });

    sidebarServicesList.querySelectorAll(".btn-del-row").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const idx = parseInt(e.currentTarget.getAttribute("data-idx"), 10);
        currentServices.splice(idx, 1);
        renderSidebarServices();
      });
    });
  }

  btnSidebarAddService.addEventListener("click", () => {
    currentServices.push({ name: "Special Dental Service", price_pkr: 3000 });
    renderSidebarServices();
  });

  renderSidebarServices();

  // =========================================================================
  // 4. Voice Recording & Waveform Visualizer (Clone Mode)
  // =========================================================================

  btnSidebarStartRecord.addEventListener("click", async () => {
    try {
      getAudioContext();
      recorderMediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const audioCtx = getAudioContext();
      const source = audioCtx.createMediaStreamSource(recorderMediaStream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);

      const chunks = [];
      mediaRecorder = new MediaRecorder(recorderMediaStream);
      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };

      mediaRecorder.onstop = () => {
        recordedVoiceBlob = new Blob(chunks, { type: "audio/wav" });
        sidebarPreviewAudio.src = URL.createObjectURL(recordedVoiceBlob);
        sidebarVoicePreview.style.display = "flex";
        btnSidebarStartRecord.style.display = "inline-flex";
        btnSidebarStopRecord.style.display = "none";

        if (recorderMediaStream) {
          recorderMediaStream.getTracks().forEach(t => t.stop());
          recorderMediaStream = null;
        }
        if (waveformAnimId) {
          cancelAnimationFrame(waveformAnimId);
          waveformAnimId = null;
        }
      };

      mediaRecorder.start();
      secondsRecorded = 0;
      btnSidebarStartRecord.style.display = "none";
      btnSidebarStopRecord.style.display = "inline-flex";
      sidebarVoicePreview.style.display = "none";

      recorderTimer = setInterval(() => {
        secondsRecorded++;
        const s = String(secondsRecorded).padStart(2, "0");
        sidebarRecordTimer.textContent = `00:${s} / 00:30`;
        if (secondsRecorded >= 30) {
          stopSidebarRecording();
        }
      }, 1000);

      const canvasCtx = sidebarWaveformCanvas.getContext("2d");
      function drawWave() {
        waveformAnimId = requestAnimationFrame(drawWave);
        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        analyser.getByteFrequencyData(dataArray);

        canvasCtx.clearRect(0, 0, sidebarWaveformCanvas.width, sidebarWaveformCanvas.height);
        const barWidth = (sidebarWaveformCanvas.width / bufferLength) * 2.2;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
          const barHeight = (dataArray[i] / 255) * sidebarWaveformCanvas.height;
          canvasCtx.fillStyle = "#0d9488";
          canvasCtx.fillRect(x, sidebarWaveformCanvas.height - barHeight, barWidth - 2, barHeight);
          x += barWidth;
        }
      }
      drawWave();

    } catch (err) {
      alert("Microphone permission required for voice cloning: " + err.message);
    }
  });

  function stopSidebarRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
      clearInterval(recorderTimer);
    }
  }

  btnSidebarStopRecord.addEventListener("click", stopSidebarRecording);

  btnSidebarRerecord.addEventListener("click", () => {
    sidebarVoicePreview.style.display = "none";
    recordedVoiceBlob = null;
    sidebarRecordTimer.textContent = "00:00 / 00:30";
  });

  // =========================================================================
  // 5. Apply & Save Agent Profile (Session Initialization)
  // =========================================================================

  agentConfigForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await initializeOrUpdateSession(true);
  });

  async function initializeOrUpdateSession(userClicked = false) {
    getAudioContext();

    // Read current services
    const serviceRows = sidebarServicesList.querySelectorAll(".sidebar-service-row");
    const collectedServices = [];
    serviceRows.forEach(row => {
      const name = row.querySelector(".svc-name").value.trim();
      const price = parseInt(row.querySelector(".svc-price").value, 10) || 0;
      if (name) collectedServices.push({ name, price_pkr: price });
    });

    const agentName = inputAgentName.value.trim() || "Zoya";
    const agentRole = inputAgentRole.value.trim() || "Front Desk Receptionist";
    const tone = document.querySelector('input[name="agent-tone"]:checked')?.value || "warm_punjabi";
    const presetVoice = document.querySelector('input[name="preset-voice"]:checked')?.value || "ur-PK-UzmaNeural";
    const voiceSpeed = parseFloat(sidebarVoiceSpeed.value) || 1.0;
    const bizName = inputBizName.value.trim() || "SmileCare Dental Clinic";
    const bizCategory = inputBizCategory.value.trim() || "Dental Clinic";
    const bizDesc = inputBizDescription.value.trim();
    const bizLocation = inputBizLocation.value.trim();
    const bizHours = inputBizHours.value.trim();
    const fallbackResponse = inputFallbackResponse.value.trim();

    // Update Console Header
    consoleAgentName.textContent = agentName;
    consoleAgentTitle.textContent = `${agentRole} • `;
    consoleBizName.textContent = bizName;
    agentAvatarInitials.textContent = agentName.slice(0, 2).toUpperCase();
    updateConsoleVoiceBadge();

    const formData = new FormData();
    formData.append("agent_name", agentName);
    formData.append("business_name", bizName);
    formData.append("category", bizCategory);
    formData.append("description", bizDesc);
    formData.append("location", bizLocation);
    formData.append("hours", bizHours);
    formData.append("services_json", JSON.stringify(collectedServices));
    formData.append("fallback_response", fallbackResponse);
    formData.append("tone", tone);
    formData.append("voice_mode", activeVoiceMode);
    formData.append("preset_voice", presetVoice);
    formData.append("voice_speed", voiceSpeed);

    if (activeVoiceMode === "clone" && recordedVoiceBlob) {
      formData.append("voice_file", recordedVoiceBlob, "voice_reference.wav");
    }

    if (userClicked) {
      btnUpdateAgent.disabled = true;
      btnUpdateAgent.innerHTML = `<span class="ocr-spinner"></span> <span>Applying Profile...</span>`;
    }

    try {
      const res = await fetch("/api/demo/session", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();
      currentSessionId = data.session_id;
      welcomeAudioB64 = data.welcome_audio_b64 || "";

      // Update welcome bubble
      welcomeSpeakerLabel.textContent = `${data.agent_name || agentName} • ${agentRole}`;
      welcomeTextDisplay.textContent = data.welcome_text;

      // Dynamic suggestion chips update
      updateSuggestionChips(bizName, collectedServices);

      if (userClicked) {
        btnUpdateAgent.innerHTML = `<span>✓ Profile Saved & Applied!</span>`;
        setTimeout(() => {
          btnUpdateAgent.disabled = false;
          btnUpdateAgent.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg> <span>Apply & Save Agent Profile</span>`;
        }, 1800);
      }

      return data;
    } catch (err) {
      console.error("Session update error:", err);
      if (userClicked) {
        alert("Failed to apply agent profile: " + err.message);
        btnUpdateAgent.disabled = false;
        btnUpdateAgent.innerHTML = `<span>Apply & Save Agent Profile</span>`;
      }
    }
  }

  // Welcome Play button
  btnPlayWelcome.addEventListener("click", () => {
    if (welcomeAudioB64) {
      const ctx = getAudioContext();
      playAudioBuffer(welcomeAudioB64);
    }
  });

  function updateSuggestionChips(bizName, services) {
    chipsList.innerHTML = "";
    const s1 = services[0]?.name || "checkup";
    const queries = [
      { label: "Charges kya hain?", query: `${s1} ke kitne charges hain?` },
      { label: "Timing aur location?", query: "Aap ki timing aur clinic ki location bata dein?" },
      { label: "Appointment book karein", query: `Kal shaam 5 baje ${s1} ki appointment confirm kar dein.` },
      { label: "Test Fallback (Pizza?)", query: "Kya aap pizza deliver karte hain?" }
    ];

    queries.forEach(q => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip-btn";
      b.textContent = q.label;
      b.addEventListener("click", () => {
        handleUserSpeechOrText(q.query);
      });
      chipsList.appendChild(b);
    });
  }

  // =========================================================================
  // 6. Unified Call Controller: Start / End Call (Strict Termination)
  // =========================================================================

  btnMainCallAction.addEventListener("click", async () => {
    if (!isCallActive) {
      // START CALL
      await startCallSession();
    } else {
      // END CALL
      endCallSession();
    }
  });

  async function startCallSession() {
    getAudioContext();

    if (!currentSessionId) {
      await initializeOrUpdateSession(false);
    }

    isCallActive = true;
    isMicMuted = false;

    // UI Updates
    btnMainCallAction.className = "btn-call-action end-mode";
    callBtnText.textContent = "End Call";
    btnDockMic.disabled = false;
    btnDockInterrupt.disabled = false;
    callStatePill.classList.add("active");
    callStateLabel.textContent = "Live Call Active (00:00)";

    callSecondsElapsed = 0;
    clearInterval(callTimerInterval);
    callTimerInterval = setInterval(() => {
      callSecondsElapsed++;
      const m = String(Math.floor(callSecondsElapsed / 60)).padStart(2, "0");
      const s = String(callSecondsElapsed % 60).padStart(2, "0");
      callStateLabel.textContent = `Live Call Active (${m}:${s})`;
    }, 1000);

    setDockAcousticState("listening", "Call connected • Listening to you...");

    // Play greeting if present
    if (welcomeAudioB64) {
      playAudioBuffer(welcomeAudioB64);
    }

    // Connect WebSocket & Speech Recognition
    connectCallWebSocket();
    startSpeechRecognition();
  }

  function endCallSession() {
    // 1. Immediately flag session as DEAD
    isCallActive = false;
    clearInterval(callTimerInterval);

    // 2. Unbind and abort speech recognition completely
    if (speechRecognizer) {
      speechRecognizer.onend = null;
      speechRecognizer.onresult = null;
      speechRecognizer.onerror = null;
      try { speechRecognizer.abort(); } catch (e) {}
      speechRecognizer = null;
    }

    // 3. Abort any in-flight HTTP turn request
    if (activeFetchController) {
      activeFetchController.abort();
      activeFetchController = null;
    }

    // 4. Stop any playing audio immediately
    stopAudioBufferPlayback(true);

    // 5. Close WebSocket connection
    if (ws) {
      try { ws.close(); } catch (e) {}
      ws = null;
    }

    // 6. Update UI to Call Ended state
    btnMainCallAction.className = "btn-call-action start-mode";
    callBtnText.textContent = "Start Voice Call";
    btnDockMic.disabled = true;
    btnDockInterrupt.disabled = true;
    callStatePill.classList.remove("active");
    callStateLabel.textContent = "Call Ended";
    setDockAcousticState("idle", "Call ended • Click 'Start Voice Call' or type below");

    // Add termination notice to chat
    appendSystemNotice("Call ended. The agent is disconnected.");
  }

  // Mic Mute Toggle
  btnDockMic.addEventListener("click", () => {
    if (!isCallActive) return;
    isMicMuted = !isMicMuted;

    if (isMicMuted) {
      btnDockMic.classList.add("muted");
      setDockAcousticState("idle", "Microphone muted");
    } else {
      btnDockMic.classList.remove("muted");
      setDockAcousticState("listening", "Listening to you...");
      if (!isAiSpeaking && speechRecognizer) {
        try { speechRecognizer.start(); } catch (e) {}
      }
    }
  });

  // Barge-In Interrupt Button
  btnDockInterrupt.addEventListener("click", () => {
    if (!isCallActive) return;
    stopAudioBufferPlayback(true);
    setDockAcousticState("listening", "Interrupted • Listening to you...");
  });

  // =========================================================================
  // 7. WebSocket Telephony & Speech Recognition
  // =========================================================================

  function connectCallWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/live-call/${currentSessionId}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      if (isCallActive) {
        setDockAcousticState("listening", "Connected • Listening to you...");
      }
    };

    ws.onmessage = (event) => {
      // Guard: ignore messages if call was terminated
      if (!isCallActive) return;

      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "state") {
          if (msg.status === "thinking") {
            setDockAcousticState("thinking", `${inputAgentName.value || "Agent"} is thinking...`);
          } else if (msg.status === "speaking") {
            setDockAcousticState("speaking", `${inputAgentName.value || "Agent"} is speaking...`);
          }
        } else if (msg.type === "audio_chunk") {
          if (msg.text) {
            appendChatBubble("agent", inputAgentName.value || "Agent", msg.text, msg.audio_b64);
          }
          if (msg.audio_b64 && isCallActive) {
            playAudioBuffer(msg.audio_b64);
          }
        } else if (msg.type === "receipt_generated") {
          appendReceiptCard(msg.receipt_b64, msg.receipt_data);
        } else if (msg.type === "stop_audio") {
          stopAudioBufferPlayback(false);
        }
      } catch (err) {
        console.error("WS parse error:", err);
      }
    };

    ws.onclose = () => {
      if (isCallActive) {
        setDockAcousticState("idle", "Reconnecting audio channel...");
      }
    };
  }

  function startSpeechRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      console.warn("SpeechRecognition API not available in this browser. Quick chips and text input available.");
      return;
    }

    speechRecognizer = new SpeechRec();
    speechRecognizer.continuous = true;
    speechRecognizer.interimResults = false;
    speechRecognizer.lang = "ur-PK";

    speechRecognizer.onresult = (event) => {
      if (!isCallActive || isMicMuted || isAiSpeaking || Date.now() < ignoreSpeechUntil) return;
      const lastIdx = event.results.length - 1;
      const spokenTranscript = event.results[lastIdx][0].transcript.trim();
      if (spokenTranscript.length > 0) {
        handleUserSpeechOrText(spokenTranscript);
      }
    };

    speechRecognizer.onerror = (e) => {
      console.warn("Speech recognition notice:", e.error);
    };

    speechRecognizer.onend = () => {
      // Strict guard: only restart if call is actively running
      if (isCallActive && !isMicMuted && !isAiSpeaking) {
        try { speechRecognizer.start(); } catch (err) {}
      }
    };

    try { speechRecognizer.start(); } catch (e) {}
  }

  // =========================================================================
  // 8. User Interaction Handler (Voice or Typed Text)
  // =========================================================================

  function handleUserSpeechOrText(text) {
    text = (text || "").trim();
    if (!text) return;

    // If AI is speaking, interrupt immediately
    if (isAiSpeaking) {
      stopAudioBufferPlayback(true);
    }

    // Deduplication check
    const now = Date.now();
    if (text.toLowerCase() === lastSpokenText.toLowerCase() && (now - lastSpokenTime) < 3000) {
      return;
    }
    lastSpokenText = text;
    lastSpokenTime = now;

    // Append to Chat Feed
    appendChatBubble("user", "You", text);

    // If call is active with WebSocket
    if (isCallActive && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "user_speech", text }));
    } else {
      // Fallback via HTTP REST turn
      fallbackRestTurn(text);
    }
  }

  async function fallbackRestTurn(text) {
    setDockAcousticState("thinking", `${inputAgentName.value || "Agent"} is thinking...`);
    activeFetchController = new AbortController();

    try {
      const fd = new FormData();
      fd.append("session_id", currentSessionId);
      fd.append("user_text", text);

      const res = await fetch("/api/demo/chat", {
        method: "POST",
        body: fd,
        signal: activeFetchController.signal,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();

      // Guard: do not display or speak if user hung up while request was in-flight
      if (!isCallActive && !textChatInput) return;

      if (data.reply_text) {
        appendChatBubble("agent", inputAgentName.value || "Agent", data.reply_text, data.audio_b64);
        if (data.audio_b64 && isCallActive) {
          playAudioBuffer(data.audio_b64);
        } else {
          setDockAcousticState("idle", "Ready for next message");
        }
      }

      if (data.receipt_b64) {
        appendReceiptCard(data.receipt_b64, data.receipt_data);
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setDockAcousticState("idle", "Error getting reply");
      }
    } finally {
      activeFetchController = null;
    }
  }

  // Text Chat Form Submission
  textChatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const val = textChatInput.value.trim();
    if (val) {
      textChatInput.value = "";
      handleUserSpeechOrText(val);
    }
  });

  // =========================================================================
  // 9. Chat Viewport Bubble Rendering
  // =========================================================================

  function appendChatBubble(role, speaker, text, audioB64 = null) {
    text = (text || "").trim();
    if (!text) return;

    const row = document.createElement("div");
    row.className = `chat-row ${role}-row`;

    let badgeHtml = "";
    if (role === "agent") {
      badgeHtml = `<span class="urdu-tag">اردو لہجہ</span>`;
    }

    let playBtnHtml = "";
    if (role === "agent" && audioB64) {
      playBtnHtml = `<button type="button" class="btn-play-voice">🔊 Play Voice</button>`;
    }

    row.innerHTML = `
      <div class="chat-bubble ${role}-bubble">
        <div class="cb-header">
          <span class="cb-speaker">${escapeHtml(speaker)}</span>
          <div style="display:flex;align-items:center;gap:6px;">
            ${badgeHtml}
            ${playBtnHtml}
          </div>
        </div>
        <p class="cb-text">${escapeHtml(text)}</p>
      </div>
    `;

    if (role === "agent" && audioB64) {
      const btn = row.querySelector(".btn-play-voice");
      btn?.addEventListener("click", () => {
        playAudioBuffer(audioB64);
      });
    }

    chatViewport.appendChild(row);
    chatViewport.scrollTop = chatViewport.scrollHeight;
  }

  function appendReceiptCard(receiptB64, receiptData) {
    if (!receiptB64) return;

    const row = document.createElement("div");
    row.className = "chat-row agent-row";

    const totalPkr = receiptData?.items ? receiptData.items.reduce((acc, i) => acc + (i.price_pkr * (i.qty || 1)), 0) : 5500;

    row.innerHTML = `
      <div class="chat-bubble agent-bubble" style="max-width: 90%;">
        <div class="cb-header">
          <span class="cb-speaker">Transaction Confirmed</span>
          <span class="badge badge-green">★ Verified Booking</span>
        </div>
        <div class="chat-receipt-card">
          <div class="crc-icon">🧾</div>
          <div class="crc-details">
            <strong>Physical Paper Receipt Generated</strong>
            <p>${receiptData?.business_name || "SmileCare Dental"} • Total: Rs ${totalPkr.toLocaleString()} PKR</p>
          </div>
          <div class="crc-actions">
            <button type="button" class="btn-sm-teal btn-view-receipt-action">Inspect Document</button>
          </div>
        </div>
      </div>
    `;

    row.querySelector(".btn-view-receipt-action")?.addEventListener("click", () => {
      // Update Tab 2 Receipt Image and switch
      receiptPaperImg.src = `data:image/png;base64,${receiptB64}`;
      if (receiptData && ocrJsonDisplay) {
        ocrJsonDisplay.textContent = JSON.stringify(receiptData, null, 2);
      }
      switchGlobalTab("tab-receipts");
    });

    chatViewport.appendChild(row);
    chatViewport.scrollTop = chatViewport.scrollHeight;
  }

  function appendSystemNotice(text) {
    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.justifyContent = "center";
    row.style.width = "100%";
    row.innerHTML = `
      <div style="font-size:11px;color:var(--text-muted);background:var(--bg-subtle);border:1px solid var(--border-hairline);padding:4px 12px;border-radius:var(--radius-full);">
        ${escapeHtml(text)}
      </div>
    `;
    chatViewport.appendChild(row);
    chatViewport.scrollTop = chatViewport.scrollHeight;
  }

  // =========================================================================
  // 10. Tab 2: Receipts & Multimodal OCR Inspector
  // =========================================================================

  // Download Receipt PNG
  btnDownloadReceiptPng?.addEventListener("click", () => {
    const src = receiptPaperImg.src;
    if (!src) return;
    const a = document.createElement("a");
    a.href = src;
    a.download = `receipt_${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });

  // Print Receipt
  btnPrintReceipt?.addEventListener("click", () => {
    const src = receiptPaperImg.src;
    if (!src) return;
    const printWin = window.open("", "_blank");
    if (printWin) {
      printWin.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
          <title>Physical Paper Receipt</title>
          <style>
            body { margin: 0; display: flex; justify-content: center; align-items: center; background: #fff; min-height: 100vh; }
            img { max-width: 380px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
          </style>
        </head>
        <body>
          <img src="${src}" onload="window.print(); window.close();" />
        </body>
        </html>
      `);
      printWin.document.close();
    }
  });

  // OCR Upload
  btnBrowseOcr?.addEventListener("click", () => ocrFileInput.click());

  ocrFileInput?.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) {
      processOcrFile(e.target.files[0]);
    }
  });

  if (ocrDropzone) {
    ocrDropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      ocrDropzone.classList.add("drag-over");
    });
    ocrDropzone.addEventListener("dragleave", () => {
      ocrDropzone.classList.remove("drag-over");
    });
    ocrDropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      ocrDropzone.classList.remove("drag-over");
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        processOcrFile(e.dataTransfer.files[0]);
      }
    });
  }

  async function processOcrFile(file) {
    if (!file) return;

    ocrStatusBar.style.display = "flex";
    ocrStatusText.textContent = "Analyzing document image and extracting verified schema...";

    const formData = new FormData();
    formData.append("image_file", file);

    try {
      const res = await fetch("/api/demo/receipt/ocr", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (data.status === "success" && data.extracted_data) {
        ocrJsonDisplay.textContent = JSON.stringify(data.extracted_data, null, 2);
        ocrStatusText.textContent = "✓ Receipt verified and parsed successfully!";
        setTimeout(() => {
          ocrStatusBar.style.display = "none";
        }, 2200);
      } else {
        throw new Error(data.message || "Failed to parse receipt image");
      }
    } catch (err) {
      ocrStatusText.textContent = "OCR extraction error: " + err.message;
    }
  }

  // =========================================================================
  // 11. Tab: Tools & Skills Marketplace (Demo Ecosystem)
  // =========================================================================
  const toolsGridCards = document.getElementById("tools-grid-cards");
  const toolSimModal = document.getElementById("tool-sim-modal");
  const simToolIcon = document.getElementById("sim-tool-icon");
  const simToolTitle = document.getElementById("sim-tool-title");
  const simToolBadge = document.getElementById("sim-tool-badge");
  const simVisualPreviewCol = document.getElementById("sim-visual-preview-col");
  const simReceiptImg = document.getElementById("sim-receipt-img");
  const simJsonOutput = document.getElementById("sim-json-output");
  const btnCloseSim = document.getElementById("btn-close-sim");
  const btnDoneSim = document.getElementById("btn-done-sim");

  async function loadToolsCatalog() {
    if (!toolsGridCards) return;
    try {
      const url = currentSessionId ? `/api/demo/tools?session_id=${currentSessionId}` : "/api/demo/tools";
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      renderToolsCards(data.tools || []);
    } catch (e) {
      console.warn("Failed to load tools catalog:", e);
    }
  }

  function renderToolsCards(tools) {
    if (!toolsGridCards) return;
    toolsGridCards.innerHTML = "";

    tools.forEach(tool => {
      const card = document.createElement("div");
      card.className = "tool-store-card";
      const isConnected = tool.connected;

      card.innerHTML = `
        <div class="tsc-top">
          <span class="tsc-icon">${tool.icon || "⚙️"}</span>
          <span class="tsc-badge ${isConnected ? 'connected' : 'disconnected'}">
            ${isConnected ? '● Connected' : '○ Available'}
          </span>
        </div>
        <div class="tsc-content">
          <h4>${escapeHtml(tool.name)}</h4>
          <p>${escapeHtml(tool.description)}</p>
        </div>
        <div class="tsc-toggle-row">
          <span class="tsc-toggle-label">${isConnected ? 'Agent Tool: ON' : 'Agent Tool: OFF'}</span>
          <button type="button" class="btn-xs-teal btn-toggle-tool" data-id="${tool.id}" data-connected="${isConnected}">
            ${isConnected ? 'Disconnect' : 'Connect to Agent'}
          </button>
        </div>
        <button type="button" class="btn-simulate-tool" data-id="${tool.id}" data-name="${escapeHtml(tool.name)}" data-icon="${tool.icon || '⚙️'}">
          <span>⚡ Test Run Tool (Live Simulation)</span>
        </button>
      `;

      card.querySelector(".btn-toggle-tool")?.addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        const toolId = btn.dataset.id;
        const willConnect = btn.dataset.connected !== "true";
        btn.textContent = "Updating...";

        try {
          await fetch("/api/demo/tools/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tool_id: toolId, connected: willConnect, session_id: currentSessionId }),
          });
          loadToolsCatalog();
        } catch (err) {
          console.error("Tool toggle error:", err);
        }
      });

      card.querySelector(".btn-simulate-tool")?.addEventListener("click", (e) => {
        const btn = e.currentTarget;
        simulateToolRun(btn.dataset.id, btn.dataset.name, btn.dataset.icon);
      });

      toolsGridCards.appendChild(card);
    });
  }

  async function simulateToolRun(toolId, toolName, toolIcon) {
    if (!toolSimModal) return;

    toolSimModal.style.display = "block";
    simToolIcon.textContent = toolIcon || "⚙️";
    simToolTitle.textContent = `${toolName} — Execution Output`;
    simToolBadge.textContent = "Running Simulation...";
    simJsonOutput.textContent = "Triggering simulated tool API and processing business payload...";
    simVisualPreviewCol.style.display = "none";

    // Scroll to modal
    toolSimModal.scrollIntoView({ behavior: "smooth", block: "center" });

    try {
      const res = await fetch("/api/demo/tools/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool_id: toolId,
          business_name: inputBizName.value || "SmileCare Dental Clinic",
          session_id: currentSessionId,
        }),
      });

      const data = await res.json();
      simToolBadge.textContent = "✔ Successful Simulation";

      if (data.simulation_result) {
        simJsonOutput.textContent = JSON.stringify(data.simulation_result, null, 2);

        // If receipt simulation returned an image
        if (data.simulation_result.receipt_b64) {
          simReceiptImg.src = `data:image/png;base64,${data.simulation_result.receipt_b64}`;
          simVisualPreviewCol.style.display = "block";
        }
      }
    } catch (err) {
      simToolBadge.textContent = "Simulation Failed";
      simJsonOutput.textContent = "Error executing simulation: " + err.message;
    }
  }

  btnCloseSim?.addEventListener("click", () => {
    if (toolSimModal) toolSimModal.style.display = "none";
  });
  btnDoneSim?.addEventListener("click", () => {
    if (toolSimModal) toolSimModal.style.display = "none";
  });

  // Load tools on launch
  loadToolsCatalog();

  // Initial Session Kickoff
  initializeOrUpdateSession(false);

  // Helper
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});
