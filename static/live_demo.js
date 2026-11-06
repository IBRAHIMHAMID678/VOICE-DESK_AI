// Live Voice AI Receptionist Demo Client
document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const screenSetup = document.getElementById("screen-setup");
  const screenVoice = document.getElementById("screen-voice");
  const screenCall = document.getElementById("screen-call");
  const screenExport = document.getElementById("screen-export");

  // Inputs & Presets
  const bizNameInput = document.getElementById("biz-name");
  const bizCategoryInput = document.getElementById("biz-category");
  const bizLocationInput = document.getElementById("biz-location");
  const bizHoursInput = document.getElementById("biz-hours");
  const servicesList = document.getElementById("services-list");
  const btnAddService = document.getElementById("btn-add-service");
  const presetButtons = document.querySelectorAll(".preset-btn");

  // Voice recording elements
  const btnRecord = document.getElementById("btn-record");
  const btnStopRecord = document.getElementById("btn-stop-record");
  const btnReRecord = document.getElementById("btn-re-record");
  const playbackPreview = document.getElementById("playback-preview");
  const recordedAudio = document.getElementById("recorded-audio");
  const timerDisplay = document.getElementById("timer-display");
  const canvas = document.getElementById("waveform-canvas");
  const canvasCtx = canvas.getContext("2d");

  // Navigation Buttons
  const btnToVoice = document.getElementById("btn-to-voice");
  const btnBackSetup = document.getElementById("btn-back-setup");
  const btnLaunchCall = document.getElementById("btn-launch-call");
  const btnEndCall = document.getElementById("btn-end-call");
  const btnCallAgain = document.getElementById("btn-call-again");
  const btnExportWa = document.getElementById("btn-export-wa");

  // Call elements
  const callTimerText = document.getElementById("call-timer-text");
  const callVoiceMode = document.getElementById("call-voice-mode");
  const callBizTitle = document.getElementById("call-biz-title");
  const avatarText = document.getElementById("avatar-text");
  const avatarZone = document.querySelector(".call-avatar-zone");
  const agentStateDot = document.getElementById("agent-state-dot");
  const agentStateText = document.getElementById("agent-state-text");
  const miniEqualizer = document.getElementById("mini-equalizer");
  const transcriptFeed = document.getElementById("transcript-feed");
  const btnMicToggle = document.getElementById("btn-mic-toggle");
  const btnInterrupt = document.getElementById("btn-interrupt");
  const quickChips = document.querySelectorAll(".quick-chip");

  // Presets Data
  const PRESETS = {
    dental: {
      name: "SmileCare Dental Clinic",
      category: "Dental & Aesthetics",
      location: "Gulberg III, Lahore",
      hours: "11:00 AM se 9:00 PM (Monday - Saturday)",
      services: [
        { name: "Dental Checkup & Consultation", price_pkr: 1500, duration_min: 20 },
        { name: "Teeth Scaling & Polishing", price_pkr: 4000, duration_min: 30 },
        { name: "Laser Teeth Whitening", price_pkr: 12000, duration_min: 45 }
      ]
    },
    restaurant: {
      name: "Chunkyard Gourmet Burgers",
      category: "Restaurant & Delivery",
      location: "F-7 Markaz, Islamabad",
      hours: "1:00 PM se 2:00 AM (Daily)",
      services: [
        { name: "Classic Beef Zinger Burger", price_pkr: 890, duration_min: 15 },
        { name: "Smash Mushroom Patty Meal", price_pkr: 1150, duration_min: 15 },
        { name: "Loaded Cheese Fries", price_pkr: 550, duration_min: 10 }
      ]
    },
    salon: {
      name: "Glow & Glam Aesthetics",
      category: "Hair Salon & Spa",
      location: "DHA Phase 5, Karachi",
      hours: "11:00 AM se 8:00 PM (Tuesday - Sunday)",
      services: [
        { name: "HydraFacial Glow Treatment", price_pkr: 6500, duration_min: 45 },
        { name: "Keratin Hair Protein Spa", price_pkr: 14000, duration_min: 90 },
        { name: "Bridal Makeup Consultation", price_pkr: 25000, duration_min: 60 }
      ]
    },
    realestate: {
      name: "DHA Premier Estates",
      category: "Property & Investments",
      location: "DHA Phase 6, Lahore",
      hours: "10:00 AM se 7:00 PM (Monday - Saturday)",
      services: [
        { name: "1 Kanal Plot Site Visit", price_pkr: 0, duration_min: 60 },
        { name: "Commercial Investment Advisory", price_pkr: 0, duration_min: 30 },
        { name: "Rental Agreement Legal Review", price_pkr: 5000, duration_min: 45 }
      ]
    }
  };

  // State
  let currentSessionId = null;
  let recordedBlob = null;
  let mediaRecorder = null;
  let audioContext = null;
  let analyser = null;
  let animFrameId = null;
  let recordTimer = null;
  let secondsRecorded = 0;
  let callInterval = null;
  let callSeconds = 0;
  let ws = null;
  let isMuted = false;
  let recognition = null;
  let isAiSpeaking = false;
  let ignoreSpeechUntil = 0;
  let lastSpokenText = "";
  let lastSpokenTime = 0;

  // Single persistent audio player to satisfy browser autoplay policy across multi-turn calls
  const persistentAudio = new Audio();
  persistentAudio.preload = "auto";

  // Render services in list
  function renderServices(services) {
    servicesList.innerHTML = "";
    services.forEach((s, idx) => {
      const row = document.createElement("div");
      row.className = "service-item-row";
      row.innerHTML = `
        <input type="text" class="svc-name" value="${s.name}" placeholder="Service Name">
        <input type="number" class="svc-price" value="${s.price_pkr}" placeholder="Price (PKR)">
        <button type="button" class="btn-del-service" data-idx="${idx}">&times;</button>
      `;
      servicesList.appendChild(row);
    });

    document.querySelectorAll(".btn-del-service").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const idx = parseInt(e.target.dataset.idx, 10);
        services.splice(idx, 1);
        renderServices(services);
      });
    });
  }

  // Initial populate with Dental
  let activeServices = [...PRESETS.dental.services];
  renderServices(activeServices);

  // Preset Click Handlers
  presetButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      presetButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const pKey = btn.dataset.preset;
      const data = PRESETS[pKey];
      if (data) {
        bizNameInput.value = data.name;
        bizCategoryInput.value = data.category;
        bizLocationInput.value = data.location;
        bizHoursInput.value = data.hours;
        activeServices = [...data.services];
        renderServices(activeServices);
      }
    });
  });

  btnAddService.addEventListener("click", () => {
    activeServices.push({ name: "New Service", price_pkr: 2000, duration_min: 30 });
    renderServices(activeServices);
  });

  // Switch Screens
  function showScreen(screen) {
    [screenSetup, screenVoice, screenCall, screenExport].forEach(s => s.classList.remove("active"));
    screen.classList.add("active");
  }

  btnToVoice.addEventListener("click", () => showScreen(screenVoice));
  btnBackSetup.addEventListener("click", () => showScreen(screenSetup));

  // Audio Recording & Waveform Visualization
  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);

      const chunks = [];
      mediaRecorder = new MediaRecorder(stream);
      mediaRecorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
      mediaRecorder.onstop = () => {
        recordedBlob = new Blob(chunks, { type: "audio/wav" });
        recordedAudio.src = URL.createObjectURL(recordedBlob);
        playbackPreview.style.display = "flex";
        btnRecord.style.display = "flex";
        btnStopRecord.style.display = "none";
        stream.getTracks().forEach(track => track.stop());
        cancelAnimationFrame(animFrameId);
      };

      mediaRecorder.start();
      secondsRecorded = 0;
      btnRecord.style.display = "none";
      btnStopRecord.style.display = "flex";
      playbackPreview.style.display = "none";

      recordTimer = setInterval(() => {
        secondsRecorded++;
        const m = String(Math.floor(secondsRecorded / 60)).padStart(2, "0");
        const s = String(secondsRecorded % 60).padStart(2, "0");
        timerDisplay.textContent = `${m}:${s} / 00:30`;
        if (secondsRecorded >= 30) {
          stopRecording();
        }
      }, 1000);

      drawWaveform();
    } catch (err) {
      alert("Microphone permission required for voice cloning: " + err.message);
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
      clearInterval(recordTimer);
    }
  }

  function drawWaveform() {
    animFrameId = requestAnimationFrame(drawWaveform);
    if (!analyser) return;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    analyser.getByteFrequencyData(dataArray);

    canvasCtx.clearRect(0, 0, canvas.width, canvas.height);
    const barWidth = (canvas.width / bufferLength) * 2;
    let x = 0;

    for (let i = 0; i < bufferLength; i++) {
      const barHeight = (dataArray[i] / 255) * canvas.height;
      canvasCtx.fillStyle = `rgb(99, 102, 241)`;
      canvasCtx.fillRect(x, canvas.height - barHeight, barWidth - 2, barHeight);
      x += barWidth;
    }
  }

  btnRecord.addEventListener("click", startRecording);
  btnStopRecord.addEventListener("click", stopRecording);
  btnReRecord.addEventListener("click", () => {
    playbackPreview.style.display = "none";
    recordedBlob = null;
    timerDisplay.textContent = "00:00 / 00:30";
  });

  // Launch Call Button
  btnLaunchCall.addEventListener("click", async () => {
    btnLaunchCall.disabled = true;
    btnLaunchCall.textContent = "Cloning & Connecting...";

    // Unlock persistent audio player within user click gesture
    try {
      persistentAudio.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
      persistentAudio.play().then(() => persistentAudio.pause()).catch(() => {});
    } catch (e) {}

    // Collect services from current input rows
    const curServices = [];
    document.querySelectorAll(".service-item-row").forEach(row => {
      const name = row.querySelector(".svc-name").value.trim();
      const price = parseInt(row.querySelector(".svc-price").value, 10) || 0;
      if (name) curServices.push({ name, price_pkr: price, duration_min: 30 });
    });

    const formData = new FormData();
    formData.append("business_name", bizNameInput.value.trim());
    formData.append("category", bizCategoryInput.value.trim());
    formData.append("location", bizLocationInput.value.trim());
    formData.append("hours", bizHoursInput.value.trim());
    formData.append("services_json", JSON.stringify(curServices));

    if (recordedBlob) {
      formData.append("voice_file", recordedBlob, "sample.wav");
    }

    try {
      const res = await fetch("/api/demo/session", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      currentSessionId = data.session_id;

      // Update UI for Call Screen
      callBizTitle.textContent = bizNameInput.value.trim();
      const initials = bizNameInput.value.trim().split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
      avatarText.textContent = initials || "AI";
      callVoiceMode.textContent = data.has_custom_voice ? "✨ Cloned Voice Active" : "🎙️ Neural Voice Active";

      showScreen(screenCall);
      startCallSession(data.welcome_text, data.welcome_audio_b64);
    } catch (err) {
      alert("Failed to initialize session: " + err.message);
    } finally {
      btnLaunchCall.disabled = false;
      btnLaunchCall.innerHTML = `<span>Launch Live Call Demo</span>`;
    }
  });

  // Start Call Session
  function startCallSession(welcomeText, welcomeAudioB64) {
    callSeconds = 0;
    transcriptFeed.innerHTML = "";
    clearInterval(callInterval);

    callInterval = setInterval(() => {
      callSeconds++;
      const m = String(Math.floor(callSeconds / 60)).padStart(2, "0");
      const s = String(callSeconds % 60).padStart(2, "0");
      callTimerText.textContent = `Call Active (${m}:${s})`;
    }, 1000);

    // Initial greeting
    if (welcomeText) {
      addTranscript("agent", "Ayesha", welcomeText, welcomeAudioB64);
      if (welcomeAudioB64) {
        playAudio(welcomeAudioB64);
      }
    }

    // Connect WebSocket
    initWebSocket();
    // Start continuous Speech Recognition
    initSpeechRecognition();
  }

  function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/live-call/${currentSessionId}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setAgentState("Listening...", true);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "state") {
        if (data.status === "thinking") {
          setAgentState("Thinking...", false);
        } else if (data.status === "speaking") {
          setAgentState("Ayesha is speaking...", true);
        }
      } else if (data.type === "audio_chunk") {
        if (data.text) {
          addTranscript("agent", "Ayesha", data.text, data.audio_b64);
        }
        if (data.audio_b64) {
          playAudio(data.audio_b64);
        }
      } else if (data.type === "stop_audio") {
        stopAudioPlayback();
      }
    };

    ws.onclose = () => {
      setAgentState("Call ended", false);
    };
  }

  // Browser Speech Recognition for Urdu & English
  function initSpeechRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      console.warn("Browser does not support Web Speech API. Quick prompt buttons are available.");
      return;
    }

    recognition = new SpeechRec();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = "ur-PK";

    recognition.onresult = (event) => {
      if (isMuted || isAiSpeaking || Date.now() < ignoreSpeechUntil) return;
      const last = event.results.length - 1;
      const transcript = event.results[last][0].transcript.trim();
      if (transcript.length > 0) {
        handleUserSpoke(transcript);
      }
    };

    recognition.onerror = (e) => {
      console.warn("Speech recognition notice:", e.error);
    };

    recognition.onend = () => {
      if (screenCall.classList.contains("active") && !isMuted && !isAiSpeaking) {
        try { recognition.start(); } catch (err) {}
      }
    };

    try { recognition.start(); } catch (e) {}
  }

  function handleUserSpoke(text) {
    text = text.trim();
    if (!text) return;
    if (isAiSpeaking) return;

    const now = Date.now();
    // Prevent duplicate consecutive submissions within 3.5 seconds
    if (text.toLowerCase() === lastSpokenText.toLowerCase() && (now - lastSpokenTime) < 3500) {
      console.log("Ignored duplicate user speech:", text);
      return;
    }
    lastSpokenText = text;
    lastSpokenTime = now;

    // Barge-in: if AI is speaking, stop it immediately
    stopAudioPlayback();
    addTranscript("user", "You", text);

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "user_speech", text }));
    } else {
      // Fallback via HTTP REST
      fallbackRestTurn(text);
    }
  }

  async function fallbackRestTurn(text) {
    setAgentState("Thinking...", false);
    try {
      const fd = new FormData();
      fd.append("session_id", currentSessionId);
      fd.append("user_text", text);
      const res = await fetch("/api/demo/chat", { method: "POST", body: fd });
      const data = await res.json();
      if (data.reply_text) {
        addTranscript("agent", "Ayesha", data.reply_text, data.audio_b64);
        setAgentState("Ayesha is speaking...", true);
        if (data.audio_b64) {
          playAudio(data.audio_b64);
        }
      }
    } catch (e) {
      setAgentState("Error getting reply", false);
    }
  }

  // Audio Playback & Barge-In
  function playAudio(b64) {
    if (!b64) {
      console.warn("playAudio called without audio b64");
      return;
    }
    stopAudioPlayback();
    isAiSpeaking = true;
    avatarZone.classList.add("speaking");
    setAgentState("Ayesha is speaking...", true, true);

    // Temporarily pause speech recognition while AI is speaking so it doesn't transcribe itself
    if (recognition) {
      try { recognition.abort(); } catch (e) {}
    }

    persistentAudio.src = "data:audio/mpeg;base64," + b64;

    persistentAudio.onended = () => {
      isAiSpeaking = false;
      avatarZone.classList.remove("speaking");
      setAgentState("Listening...", true, false);
      // Brief cooldown before resuming recognition so speaker echo isn't picked up
      ignoreSpeechUntil = Date.now() + 500;
      setTimeout(() => {
        if (screenCall.classList.contains("active") && !isMuted) {
          try { recognition.start(); } catch (e) {}
        }
      }, 300);
    };

    persistentAudio.onerror = (e) => {
      console.error("Audio playback error:", e);
      isAiSpeaking = false;
      avatarZone.classList.remove("speaking");
      setAgentState("Listening...", true, false);
      if (screenCall.classList.contains("active") && !isMuted) {
        try { recognition.start(); } catch (err) {}
      }
    };

    const playPromise = persistentAudio.play();
    if (playPromise !== undefined) {
      playPromise.catch((err) => {
        console.warn("Browser autoplay notice:", err);
        isAiSpeaking = false;
        avatarZone.classList.remove("speaking");
        setAgentState("Tap [🔊 Replay] if audio was silenced", false, false);
      });
    }
  }

  function stopAudioPlayback() {
    if (persistentAudio) {
      persistentAudio.pause();
      persistentAudio.currentTime = 0;
    }
    isAiSpeaking = false;
    avatarZone.classList.remove("speaking");
    setAgentState("Listening...", true, false);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "interruption" }));
    }
  }

  // Interruption Button
  btnInterrupt.addEventListener("click", () => {
    stopAudioPlayback();
    setAgentState("Listening...", true);
  });

  // Mic Mute Toggle
  btnMicToggle.addEventListener("click", () => {
    isMuted = !isMuted;
    const label = btnMicToggle.querySelector(".dock-btn-label");
    if (isMuted) {
      btnMicToggle.classList.remove("active");
      btnMicToggle.classList.add("muted");
      if (label) label.textContent = "Muted";
      setAgentState("Microphone muted", false, false);
    } else {
      btnMicToggle.classList.add("active");
      btnMicToggle.classList.remove("muted");
      if (label) label.textContent = "Mic On";
      setAgentState("Listening...", true, false);
    }
  });

  // Quick Prompt Chips
  quickChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const q = chip.dataset.query;
      if (q) handleUserSpoke(q);
    });
  });

  // End Call
  btnEndCall.addEventListener("click", () => {
    clearInterval(callInterval);
    stopAudioPlayback();
    if (recognition) {
      try { recognition.stop(); } catch (e) {}
    }
    if (ws) {
      try { ws.close(); } catch (e) {}
    }
    showScreen(screenExport);
  });

  btnCallAgain.addEventListener("click", () => {
    showScreen(screenSetup);
  });

  // WhatsApp Export
  btnExportWa.addEventListener("click", async () => {
    if (!currentSessionId) return;
    btnExportWa.textContent = "Exporting...";
    try {
      const fd = new FormData();
      fd.append("session_id", currentSessionId);
      const res = await fetch("/api/demo/export-whatsapp", { method: "POST", body: fd });
      const data = await res.json();
      if (data.status === "success") {
        btnExportWa.textContent = "✓ Config Saved!";
        btnExportWa.style.background = "#059669";
        alert(`Exported successfully! Generated client config: businesses/${data.file}. Your WhatsApp number can now answer in this profile!`);
      }
    } catch (e) {
      alert("Export failed: " + e.message);
      btnExportWa.textContent = "Export Config";
    }
  });

  // Helpers
  function setAgentState(text, isActive, isSpeaking = false) {
    agentStateText.textContent = text;
    if (isActive) {
      agentStateDot.classList.add("active");
    } else {
      agentStateDot.classList.remove("active");
    }
    if (miniEqualizer) {
      if (isSpeaking) {
        miniEqualizer.classList.add("active");
      } else {
        miniEqualizer.classList.remove("active");
      }
    }
  }

  function addTranscript(role, speaker, text, audioB64 = null) {
    text = (text || "").trim();
    if (!text) return;

    // Check if the immediately preceding message is an exact duplicate
    const lastMsg = transcriptFeed.lastElementChild;
    if (lastMsg && lastMsg.dataset.text === text && lastMsg.dataset.role === role) {
      return;
    }

    const msg = document.createElement("div");
    msg.className = `transcript-msg ${role}`;
    msg.dataset.role = role;
    msg.dataset.text = text;
    
    let playBtnHtml = "";
    if (role === "agent" && audioB64) {
      playBtnHtml = `<button type="button" class="btn-play-voice-turn" title="Listen to this voice turn">🔊 Replay</button>`;
    }

    let badgeHtml = "";
    if (role === "agent") {
      badgeHtml = `<span class="urdu-badge">اردو • Lahori Warmth</span>`;
    }

    msg.innerHTML = `
      <div class="msg-header-row">
        <span class="speaker-tag">${speaker}</span>
        ${badgeHtml}
        ${playBtnHtml}
      </div>
      <p>${text}</p>
    `;

    if (role === "agent" && audioB64) {
      const btn = msg.querySelector(".btn-play-voice-turn");
      if (btn) {
        btn.addEventListener("click", () => {
          playAudio(audioB64);
        });
      }
    }

    transcriptFeed.appendChild(msg);
    transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
  }
});

