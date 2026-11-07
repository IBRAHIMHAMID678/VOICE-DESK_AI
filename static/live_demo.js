// VoiceDesk AI — Autonomous Pakistani Voice Receptionist & Transaction Documents Platform
// Architecture: Full-duplex Web Audio API buffer scheduling, Whisper ground-truth voice cloning,
// zero-hallucination fallback guardrails, and physical paper receipt generation with OCR inspector.

document.addEventListener("DOMContentLoaded", () => {
  // =========================================================================
  // DOM References
  // =========================================================================

  // Global Navigation Tabs & Panes
  const tabButtons = document.querySelectorAll(".nav-tabs .tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");

  // Step Views in Tab 1 (Agent Studio)
  const viewBuilder = document.getElementById("view-builder");
  const viewCall = document.getElementById("view-call");

  // Form Elements (Agent Builder)
  const formAgentBuilder = document.getElementById("agent-builder-form");
  const inputAgentName = document.getElementById("agent-name");
  const inputAgentRole = document.getElementById("agent-role");
  const toneRadioCards = document.querySelectorAll(".radio-card");
  const voiceModeTabs = document.querySelectorAll(".mode-tab");
  const panelVoiceClone = document.getElementById("panel-voice-clone");
  const panelVoicePreset = document.getElementById("panel-voice-preset");
  const voiceTiles = document.querySelectorAll(".voice-tile");
  const voiceSpeedSlider = document.getElementById("voice-speed");
  const speedValDisplay = document.getElementById("speed-val");

  // Voice Recorder Elements (Zero-Shot Clone)
  const btnStartRecord = document.getElementById("btn-start-record");
  const btnStopRecord = document.getElementById("btn-stop-record");
  const btnRerecord = document.getElementById("btn-rerecord");
  const recorderTimerDisplay = document.getElementById("recorder-timer");
  const waveformCanvas = document.getElementById("waveform-canvas");
  const voicePreviewRow = document.getElementById("voice-preview-row");
  const recordedPreviewAudio = document.getElementById("recorded-preview-audio");

  // Business Profile Inputs
  const inputBizName = document.getElementById("biz-name");
  const inputBizCategory = document.getElementById("biz-category");
  const inputBizDescription = document.getElementById("biz-description");
  const inputBizLocation = document.getElementById("biz-location");
  const inputBizHours = document.getElementById("biz-hours");
  const servicesTable = document.getElementById("services-table");
  const btnAddServiceRow = document.getElementById("btn-add-service-row");
  const inputFallbackResponse = document.getElementById("fallback-response");
  const btnDeployAgent = document.getElementById("btn-deploy-agent");

  // Live Call Room Elements
  const callTimerDisplay = document.getElementById("call-timer-display");
  const agentVoiceBadge = document.getElementById("agent-voice-badge");
  const btnExitToBuilder = document.getElementById("btn-exit-to-builder");
  const avatarInitialsDisplay = document.getElementById("avatar-initials-display");
  const agentDisplayName = document.getElementById("agent-display-name");
  const agentDisplayRole = document.getElementById("agent-display-role");
  const agentBizLabel = document.getElementById("agent-biz-label");
  const telephonyDisc = document.getElementById("telephony-disc");
  const telephonyAvatarConsole = document.querySelector(".telephony-avatar-console");
  const acousticDot = document.getElementById("acoustic-dot");
  const acousticStatusText = document.getElementById("acoustic-status-text");
  const equalizerBars = document.getElementById("equalizer-bars");
  const callTranscriptViewport = document.getElementById("call-transcript-viewport");
  const btnToggleMic = document.getElementById("btn-toggle-mic");
  const btnCallInterrupt = document.getElementById("btn-call-interrupt");
  const btnHangupCall = document.getElementById("btn-hangup-call");
  const dynamicChipsScroll = document.getElementById("dynamic-chips-scroll");
  const liveReceiptBanner = document.getElementById("live-receipt-banner");
  const btnViewLiveReceipt = document.getElementById("btn-view-live-receipt");

  // Receipts & OCR Tab Elements
  const btnDownloadReceiptPng = document.getElementById("btn-download-receipt-png");
  const btnPrintReceipt = document.getElementById("btn-print-receipt");
  const receiptPaperImg = document.getElementById("receipt-paper-img");
  const ocrDropzone = document.getElementById("ocr-dropzone");
  const ocrFileInput = document.getElementById("ocr-file-input");
  const btnBrowseOcr = document.getElementById("btn-browse-ocr");
  const ocrStatusRow = document.getElementById("ocr-status-row");
  const ocrStatusMsg = document.getElementById("ocr-status-msg");
  const ocrResultsBox = document.getElementById("ocr-results-box");
  const ocrJsonDisplay = document.getElementById("ocr-json-display");

  // =========================================================================
  // State Management
  // =========================================================================
  let currentSessionId = null;
  let activeVoiceMode = "clone"; // "clone" or "preset"
  let recordedVoiceBlob = null;
  let mediaRecorder = null;
  let recorderStream = null;
  let recorderTimer = null;
  let secondsRecorded = 0;
  let waveformAnimId = null;

  // Web Audio API State (guarantees continuous playback without turn-2 drops)
  let audioContext = null;
  let currentSourceNode = null;
  let isAiSpeaking = false;
  let ignoreSpeechUntil = 0;
  let lastSpokenText = "";
  let lastSpokenTime = 0;

  // Call & Speech State
  let callTimerInterval = null;
  let callSecondsElapsed = 0;
  let ws = null;
  let isMicMuted = false;
  let speechRecognizer = null;
  let currentAgentProfile = null;

  // Default Services Seed
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

  // Decodes base64 MP3 and plays it through AudioContext
  async function playAudioBuffer(base64Mp3) {
    if (!base64Mp3) return;

    const ctx = getAudioContext();
    stopAudioBufferPlayback(false);

    try {
      // Decode Base64 to ArrayBuffer
      const binaryString = atob(base64Mp3);
      const len = binaryString.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      const audioBuffer = await ctx.decodeAudioData(bytes.buffer.slice(0));

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);

      currentSourceNode = source;
      isAiSpeaking = true;

      // Update UI for speaking state
      setAcousticState("speaking", `${currentAgentProfile?.agent_name || "Agent"} is speaking...`);

      // Temporarily halt speech recognition so the mic doesn't capture speaker output
      if (speechRecognizer) {
        try { speechRecognizer.abort(); } catch (e) {}
      }

      source.onended = () => {
        if (currentSourceNode === source) {
          currentSourceNode = null;
        }
        isAiSpeaking = false;
        setAcousticState("listening", "Listening to you...");

        // Cooldown buffer to avoid picking up room reverberation
        ignoreSpeechUntil = Date.now() + 450;
        setTimeout(() => {
          if (viewCall.classList.contains("active") && !isMicMuted && !isAiSpeaking) {
            try { speechRecognizer?.start(); } catch (e) {}
          }
        }, 300);
      };

      source.start(0);
    } catch (err) {
      console.error("Web Audio API decode/playback failed:", err);
      isAiSpeaking = false;
      setAcousticState("listening", "Listening to you...");
      if (viewCall.classList.contains("active") && !isMicMuted) {
        try { speechRecognizer?.start(); } catch (e) {}
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
    setAcousticState("listening", "Listening to you...");

    if (notifyServer && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "interruption" }));
    }
  }

  function setAcousticState(mode, message) {
    if (acousticStatusText) acousticStatusText.textContent = message;

    if (mode === "speaking") {
      if (acousticDot) acousticDot.classList.add("active");
      if (equalizerBars) equalizerBars.classList.add("active");
      if (telephonyAvatarConsole) telephonyAvatarConsole.classList.add("speaking");
    } else if (mode === "thinking") {
      if (acousticDot) acousticDot.classList.add("active");
      if (equalizerBars) equalizerBars.classList.remove("active");
      if (telephonyAvatarConsole) telephonyAvatarConsole.classList.remove("speaking");
    } else {
      // listening or idle
      if (acousticDot) acousticDot.classList.toggle("active", !isMicMuted);
      if (equalizerBars) equalizerBars.classList.remove("active");
      if (telephonyAvatarConsole) telephonyAvatarConsole.classList.remove("speaking");
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

  // =========================================================================
  // 3. Agent Studio: Form Controls, Tones, and Dynamic Services
  // =========================================================================

  // Tone Selection
  toneRadioCards.forEach(card => {
    card.addEventListener("click", () => {
      toneRadioCards.forEach(c => c.classList.remove("active"));
      card.classList.add("active");
      const radio = card.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // Voice Mode Switching (Clone vs Studio Presets)
  voiceModeTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      voiceModeTabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      activeVoiceMode = tab.getAttribute("data-vmode");

      if (activeVoiceMode === "clone") {
        panelVoiceClone.classList.add("active");
        panelVoiceClone.style.display = "block";
        panelVoicePreset.classList.remove("active");
        panelVoicePreset.style.display = "none";
      } else {
        panelVoicePreset.classList.add("active");
        panelVoicePreset.style.display = "block";
        panelVoiceClone.classList.remove("active");
        panelVoiceClone.style.display = "none";
      }
    });
  });

  // Studio Voice Tile Selection
  voiceTiles.forEach(tile => {
    tile.addEventListener("click", () => {
      voiceTiles.forEach(t => t.classList.remove("active"));
      tile.classList.add("active");
      const radio = tile.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // Speech Speed Slider
  if (voiceSpeedSlider && speedValDisplay) {
    voiceSpeedSlider.addEventListener("input", () => {
      speedValDisplay.textContent = `${parseFloat(voiceSpeedSlider.value).toFixed(2)}x`;
    });
  }

  // Dynamic Services Rows
  function renderServiceRows() {
    servicesTable.innerHTML = "";
    currentServices.forEach((svc, index) => {
      const row = document.createElement("div");
      row.className = "service-row";
      row.innerHTML = `
        <input type="text" class="svc-name" value="${escapeHtml(svc.name)}" placeholder="Service / Item name">
        <input type="number" class="svc-price" value="${svc.price_pkr}" placeholder="Price (PKR)">
        <button type="button" class="btn-del-item" data-idx="${index}" title="Remove item">&times;</button>
      `;
      servicesTable.appendChild(row);
    });

    servicesTable.querySelectorAll(".btn-del-item").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const idx = parseInt(e.currentTarget.getAttribute("data-idx"), 10);
        currentServices.splice(idx, 1);
        renderServiceRows();
      });
    });
  }

  btnAddServiceRow.addEventListener("click", () => {
    currentServices.push({ name: "New Dental Service", price_pkr: 2500 });
    renderServiceRows();
  });

  // Render initial items
  renderServiceRows();

  // =========================================================================
  // 4. Voice Recording & Real-Time Waveform Visualizer (Clone Mode)
  // =========================================================================

  btnStartRecord.addEventListener("click", async () => {
    try {
      getAudioContext();
      recorderStream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const audioCtx = getAudioContext();
      const source = audioCtx.createMediaStreamSource(recorderStream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);

      const chunks = [];
      mediaRecorder = new MediaRecorder(recorderStream);
      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };

      mediaRecorder.onstop = () => {
        recordedVoiceBlob = new Blob(chunks, { type: "audio/wav" });
        recordedPreviewAudio.src = URL.createObjectURL(recordedVoiceBlob);
        voicePreviewRow.style.display = "flex";
        btnStartRecord.style.display = "inline-flex";
        btnStopRecord.style.display = "none";

        if (recorderStream) {
          recorderStream.getTracks().forEach(t => t.stop());
          recorderStream = null;
        }
        if (waveformAnimId) {
          cancelAnimationFrame(waveformAnimId);
          waveformAnimId = null;
        }
      };

      mediaRecorder.start();
      secondsRecorded = 0;
      btnStartRecord.style.display = "none";
      btnStopRecord.style.display = "inline-flex";
      voicePreviewRow.style.display = "none";

      recorderTimer = setInterval(() => {
        secondsRecorded++;
        const s = String(secondsRecorded).padStart(2, "0");
        recorderTimerDisplay.textContent = `00:${s} / 00:30`;
        if (secondsRecorded >= 30) {
          stopRecording();
        }
      }, 1000);

      // Real-time canvas waveform drawing
      const canvasCtx = waveformCanvas.getContext("2d");
      function drawWave() {
        waveformAnimId = requestAnimationFrame(drawWave);
        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        analyser.getByteFrequencyData(dataArray);

        canvasCtx.clearRect(0, 0, waveformCanvas.width, waveformCanvas.height);
        const barWidth = (waveformCanvas.width / bufferLength) * 2.2;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
          const barHeight = (dataArray[i] / 255) * waveformCanvas.height;
          // Gradient in warm amber
          const grad = canvasCtx.createLinearGradient(0, waveformCanvas.height, 0, 0);
          grad.addColorStop(0, "#f59e0b");
          grad.addColorStop(1, "#fbbf24");
          canvasCtx.fillStyle = grad;
          canvasCtx.fillRect(x, waveformCanvas.height - barHeight, barWidth - 3, barHeight);
          x += barWidth;
        }
      }
      drawWave();

    } catch (err) {
      alert("Microphone permission required for voice cloning: " + err.message);
    }
  });

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
      clearInterval(recorderTimer);
    }
  }

  btnStopRecord.addEventListener("click", stopRecording);

  btnRerecord.addEventListener("click", () => {
    voicePreviewRow.style.display = "none";
    recordedVoiceBlob = null;
    recorderTimerDisplay.textContent = "00:00 / 00:30";
  });

  // =========================================================================
  // 5. Agent Deployment & Session Initialization
  // =========================================================================

  formAgentBuilder.addEventListener("submit", async (e) => {
    e.preventDefault();

    // Unlock Web Audio API inside user click gesture
    getAudioContext();

    // Read current values from services table
    const serviceRows = servicesTable.querySelectorAll(".service-row");
    const collectedServices = [];
    serviceRows.forEach(row => {
      const name = row.querySelector(".svc-name").value.trim();
      const price = parseInt(row.querySelector(".svc-price").value, 10) || 0;
      if (name) {
        collectedServices.push({ name, price_pkr: price });
      }
    });

    const agentName = inputAgentName.value.trim() || "Zoya";
    const agentRole = inputAgentRole.value.trim() || "Front Desk Receptionist";
    const selectedToneRadio = document.querySelector('input[name="agent-tone"]:checked');
    const tone = selectedToneRadio ? selectedToneRadio.value : "warm_punjabi";
    const selectedPresetVoiceRadio = document.querySelector('input[name="preset-voice"]:checked');
    const presetVoice = selectedPresetVoiceRadio ? selectedPresetVoiceRadio.value : "ur-PK-UzmaNeural";
    const voiceSpeed = parseFloat(voiceSpeedSlider.value) || 1.0;
    const bizName = inputBizName.value.trim();
    const bizCategory = inputBizCategory.value.trim();
    const bizDesc = inputBizDescription.value.trim();
    const bizLocation = inputBizLocation.value.trim();
    const bizHours = inputBizHours.value.trim();
    const fallbackResponse = inputFallbackResponse.value.trim();

    currentAgentProfile = {
      agent_name: agentName,
      role: agentRole,
      tone,
      voice_mode: activeVoiceMode,
      preset_voice: presetVoice,
      voice_speed: voiceSpeed,
      business_name: bizName,
      category: bizCategory,
      description: bizDesc,
      location: bizLocation,
      hours: bizHours,
      services: collectedServices,
      fallback_response: fallbackResponse,
    };

    btnDeployAgent.disabled = true;
    btnDeployAgent.innerHTML = `
      <span class="ocr-spinner"></span>
      <span>Cloning Voice & Connecting Agent...</span>
    `;

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

    try {
      const res = await fetch("/api/demo/session", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      currentSessionId = data.session_id;

      // Update Live Call Room UI
      agentDisplayName.textContent = data.agent_name || agentName;
      agentDisplayRole.textContent = agentRole;
      agentBizLabel.textContent = bizName;
      avatarInitialsDisplay.textContent = (data.agent_name || agentName).slice(0, 2).toUpperCase();
      agentVoiceBadge.textContent = data.voice_label || (data.has_custom_voice ? "★ Cloned Voice Active" : "Studio Neural Active");

      // Generate dynamic test chips based on user configuration
      generateDynamicTestChips(bizName, collectedServices, bizHours);

      // Switch view from Builder to Call
      viewBuilder.classList.remove("active");
      viewCall.classList.add("active");

      // Start Call Session with Greeting
      startCallSession(data.welcome_text, data.welcome_audio_b64);

    } catch (err) {
      alert("Failed to initialize voice agent session: " + err.message);
    } finally {
      btnDeployAgent.disabled = false;
      btnDeployAgent.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>
        <span>Launch Live Phone Call with Agent</span>
      `;
    }
  });

  // Dynamic Suggestion Chips
  function generateDynamicTestChips(bizName, services, hours) {
    dynamicChipsScroll.innerHTML = "";
    const chips = [
      { label: "Timing kya hai?", query: "Aap ki timing kya hai aur clinic kahan hai?" },
      { label: "Pricing maloom karni hai", query: `Kya aap mujhe ${services[0]?.name || "services"} ki charges bata sakti hain?` },
      { label: "Appointment book karna hai", query: `Ji main kal ke liye ${services[0]?.name || "appointment"} book karwana chahta hoon.` },
      { label: "Unknown Query (Test Fallback)", query: "Kya aap home delivery ya pizza bhi supply karte hain?" }
    ];

    chips.forEach(c => {
      const chipBtn = document.createElement("button");
      chipBtn.type = "button";
      chipBtn.className = "prompt-chip";
      chipBtn.textContent = c.label;
      chipBtn.addEventListener("click", () => {
        handleUserSpeechInput(c.query);
      });
      dynamicChipsScroll.appendChild(chipBtn);
    });
  }

  // =========================================================================
  // 6. Live Call Session Execution
  // =========================================================================

  function startCallSession(welcomeText, welcomeAudioB64) {
    callSecondsElapsed = 0;
    callTranscriptViewport.innerHTML = "";
    liveReceiptBanner.style.display = "none";
    clearInterval(callTimerInterval);

    callTimerInterval = setInterval(() => {
      callSecondsElapsed++;
      const m = String(Math.floor(callSecondsElapsed / 60)).padStart(2, "0");
      const s = String(callSecondsElapsed % 60).padStart(2, "0");
      callTimerDisplay.textContent = `Call Active (${m}:${s})`;
    }, 1000);

    // Initial greeting
    if (welcomeText) {
      addTranscriptBubble("agent", currentAgentProfile?.agent_name || "Agent", welcomeText, welcomeAudioB64);
      if (welcomeAudioB64) {
        playAudioBuffer(welcomeAudioB64);
      }
    }

    // Connect WebSocket & Speech Recognition
    connectCallWebSocket();
    startSpeechRecognition();
  }

  function connectCallWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/live-call/${currentSessionId}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setAcousticState("listening", "Call connected • Listening...");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "state") {
          if (msg.status === "thinking") {
            setAcousticState("thinking", `${currentAgentProfile?.agent_name || "Agent"} is thinking...`);
          } else if (msg.status === "speaking") {
            setAcousticState("speaking", `${currentAgentProfile?.agent_name || "Agent"} is speaking...`);
          }
        } else if (msg.type === "audio_chunk") {
          if (msg.text) {
            addTranscriptBubble("agent", currentAgentProfile?.agent_name || "Agent", msg.text, msg.audio_b64);
          }
          if (msg.audio_b64) {
            playAudioBuffer(msg.audio_b64);
          }
        } else if (msg.type === "receipt_generated") {
          handleReceiptGeneratedEvent(msg.receipt_b64, msg.receipt_data);
        } else if (msg.type === "stop_audio") {
          stopAudioBufferPlayback(false);
        }
      } catch (err) {
        console.error("Error processing websocket payload:", err);
      }
    };

    ws.onclose = () => {
      setAcousticState("idle", "Call ended");
    };
  }

  // Handle Automatic Physical Receipt Event
  function handleReceiptGeneratedEvent(receiptB64, receiptData) {
    if (liveReceiptBanner) {
      liveReceiptBanner.style.display = "flex";
    }

    if (receiptB64 && receiptPaperImg) {
      receiptPaperImg.src = `data:image/png;base64,${receiptB64}`;
    }

    if (receiptData && ocrJsonDisplay) {
      ocrJsonDisplay.textContent = JSON.stringify(receiptData, null, 2);
    }
  }

  // Switch to Receipt Tab on Banner Button Click
  if (btnViewLiveReceipt) {
    btnViewLiveReceipt.addEventListener("click", () => {
      switchGlobalTab("tab-receipts");
    });
  }

  // =========================================================================
  // 7. Continuous Speech Recognition (Urdu + English)
  // =========================================================================

  function startSpeechRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      console.warn("SpeechRecognition API not available in this browser. Quick chips available.");
      return;
    }

    speechRecognizer = new SpeechRec();
    speechRecognizer.continuous = true;
    speechRecognizer.interimResults = false;
    speechRecognizer.lang = "ur-PK";

    speechRecognizer.onresult = (event) => {
      if (isMicMuted || isAiSpeaking || Date.now() < ignoreSpeechUntil) return;
      const lastIdx = event.results.length - 1;
      const spokenTranscript = event.results[lastIdx][0].transcript.trim();
      if (spokenTranscript.length > 0) {
        handleUserSpeechInput(spokenTranscript);
      }
    };

    speechRecognizer.onerror = (e) => {
      console.warn("Speech recognition notice:", e.error);
    };

    speechRecognizer.onend = () => {
      if (viewCall.classList.contains("active") && !isMicMuted && !isAiSpeaking) {
        try { speechRecognizer.start(); } catch (err) {}
      }
    };

    try { speechRecognizer.start(); } catch (e) {}
  }

  function handleUserSpeechInput(text) {
    text = (text || "").trim();
    if (!text) return;
    if (isAiSpeaking) {
      // Barge-in: interrupt agent
      stopAudioBufferPlayback(true);
    }

    const now = Date.now();
    // Guard against exact repeated events within 3.2 seconds
    if (text.toLowerCase() === lastSpokenText.toLowerCase() && (now - lastSpokenTime) < 3200) {
      return;
    }
    lastSpokenText = text;
    lastSpokenTime = now;

    // Add to transcript bubble
    addTranscriptBubble("user", "You", text);

    // Send to agent via WebSocket
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "user_speech", text }));
    } else {
      // Fallback via HTTP REST
      fallbackRestTurn(text);
    }
  }

  async function fallbackRestTurn(text) {
    setAcousticState("thinking", "Agent is thinking...");
    try {
      const fd = new FormData();
      fd.append("session_id", currentSessionId);
      fd.append("user_text", text);
      const res = await fetch("/api/demo/chat", { method: "POST", body: fd });
      const data = await res.json();
      if (data.reply_text) {
        addTranscriptBubble("agent", currentAgentProfile?.agent_name || "Agent", data.reply_text, data.audio_b64);
        if (data.audio_b64) {
          playAudioBuffer(data.audio_b64);
        }
      }
    } catch (e) {
      setAcousticState("idle", "Error getting reply");
    }
  }

  // =========================================================================
  // 8. Transcript Rendering
  // =========================================================================

  function addTranscriptBubble(role, speaker, text, audioB64 = null) {
    text = (text || "").trim();
    if (!text) return;

    // Check duplicate
    const lastMsg = callTranscriptViewport.lastElementChild;
    if (lastMsg && lastMsg.dataset.text === text && lastMsg.dataset.role === role) {
      return;
    }

    const msg = document.createElement("div");
    msg.className = `call-msg ${role}`;
    msg.dataset.role = role;
    msg.dataset.text = text;

    let badgeHtml = "";
    if (role === "agent") {
      badgeHtml = `<span class="urdu-pill">اردو لہجہ</span>`;
    }

    let replayBtnHtml = "";
    if (role === "agent" && audioB64) {
      replayBtnHtml = `<button type="button" class="btn-replay-turn" title="Replay voice">🔊 Play</button>`;
    }

    msg.innerHTML = `
      <div class="cm-header">
        <span class="speaker-title">${escapeHtml(speaker)}</span>
        <div style="display:flex;align-items:center;gap:6px;">
          ${badgeHtml}
          ${replayBtnHtml}
        </div>
      </div>
      <p>${escapeHtml(text)}</p>
    `;

    if (role === "agent" && audioB64) {
      const btn = msg.querySelector(".btn-replay-turn");
      if (btn) {
        btn.addEventListener("click", () => {
          playAudioBuffer(audioB64);
        });
      }
    }

    callTranscriptViewport.appendChild(msg);
    callTranscriptViewport.scrollTop = callTranscriptViewport.scrollHeight;
  }

  // =========================================================================
  // 9. Telephony Controls (Mute, Interrupt, Hangup)
  // =========================================================================

  // Mute Button
  btnToggleMic.addEventListener("click", () => {
    isMicMuted = !isMicMuted;
    const lbl = btnToggleMic.querySelector(".dock-lbl");

    if (isMicMuted) {
      btnToggleMic.classList.remove("active");
      btnToggleMic.classList.add("muted");
      if (lbl) lbl.textContent = "Muted";
      setAcousticState("idle", "Microphone muted");
    } else {
      btnToggleMic.classList.add("active");
      btnToggleMic.classList.remove("muted");
      if (lbl) lbl.textContent = "Mic On";
      setAcousticState("listening", "Listening to you...");
      if (!isAiSpeaking && speechRecognizer) {
        try { speechRecognizer.start(); } catch (e) {}
      }
    }
  });

  // Interrupt Button
  btnCallInterrupt.addEventListener("click", () => {
    stopAudioBufferPlayback(true);
    setAcousticState("listening", "Interrupted • Listening...");
  });

  // Hangup Button
  btnHangupCall.addEventListener("click", endCallSession);

  // Exit back to Builder
  btnExitToBuilder.addEventListener("click", () => {
    endCallSession();
    viewCall.classList.remove("active");
    viewBuilder.classList.add("active");
  });

  function endCallSession() {
    clearInterval(callTimerInterval);
    stopAudioBufferPlayback(true);

    if (speechRecognizer) {
      try { speechRecognizer.stop(); } catch (e) {}
    }
    if (ws) {
      try { ws.close(); } catch (e) {}
    }

    setAcousticState("idle", "Call ended");
    callTimerDisplay.textContent = "Call Ended";
  }

  // =========================================================================
  // 10. Physical Receipts & OCR Verification Tab
  // =========================================================================

  // Download Receipt PNG
  if (btnDownloadReceiptPng) {
    btnDownloadReceiptPng.addEventListener("click", () => {
      const src = receiptPaperImg.src;
      if (!src) return;
      const a = document.createElement("a");
      a.href = src;
      a.download = `receipt_${Date.now()}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });
  }

  // Print Receipt
  if (btnPrintReceipt) {
    btnPrintReceipt.addEventListener("click", () => {
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
  }

  // OCR Dropzone & Upload
  if (btnBrowseOcr && ocrFileInput) {
    btnBrowseOcr.addEventListener("click", () => {
      ocrFileInput.click();
    });
  }

  if (ocrFileInput) {
    ocrFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        processOcrFile(e.target.files[0]);
      }
    });
  }

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

    if (ocrStatusRow) ocrStatusRow.style.display = "flex";
    if (ocrStatusMsg) ocrStatusMsg.textContent = "Analyzing document image and extracting verified schema...";

    const formData = new FormData();
    formData.append("image_file", file);

    try {
      const res = await fetch("/api/demo/receipt/ocr", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (data.status === "success" && data.extracted_data) {
        if (ocrJsonDisplay) {
          ocrJsonDisplay.textContent = JSON.stringify(data.extracted_data, null, 2);
        }
        if (ocrStatusMsg) ocrStatusMsg.textContent = "✓ Receipt verified and parsed successfully!";
        setTimeout(() => {
          if (ocrStatusRow) ocrStatusRow.style.display = "none";
        }, 2500);
      } else {
        throw new Error(data.message || "Failed to parse receipt image");
      }
    } catch (err) {
      if (ocrStatusMsg) ocrStatusMsg.textContent = "OCR extraction error: " + err.message;
    }
  }

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
