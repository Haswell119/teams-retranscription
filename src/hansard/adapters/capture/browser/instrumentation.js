// Selector literals below mirror hansard/adapters/capture/browser/selectors.py; change both together.
(() => {
  "use strict";

  if (window.__hansardInstrumented) {
    return;
  }
  window.__hansardInstrumented = true;

  const CSRC_POLL_MS = 100;
  const CSRC_RECENCY_MS = 50;
  const CSRC_HOLD_MS = 400;
  const CSRC_WINDOW = 5;
  const CSRC_MIN_HITS = 4;
  const DOM_POLL_MS = 500;
  const HEALTH_INTERVAL_MS = 15000;
  const OWNER_REFRESH_MS = 1000;
  const FLUSH_INTERVAL_MS = 500;
  const MAX_PENDING = 2000;

  const SPEAKING_INDICATOR = '[data-tid="voice-level-stream-outline"]';
  const SPEAKING_CONTAINER = "[data-stream-type][data-tid]";
  const ROSTER_PANEL = '[data-tid="roster"], [data-tid="roster-list"]';
  const ROSTER_ROW = '[data-tid="roster-participant"], [role="treeitem"]';
  const CHAIN_ID_HEADERS = ["X-Microsoft-Skype-Chain-ID", "x-microsoft-skype-chain-id"];

  const counters = {
    ws_frames: 0,
    ws_decode_failures: 0,
    roster_updates: 0,
    call_end: 0,
    csrc_polls: 0,
    csrc_transitions: 0,
    csrc_mapped: 0,
    dsh_messages: 0,
    dsh_transitions: 0,
    dom_transitions: 0,
    dom_roster_updates: 0,
    peer_connections: 0,
    data_channels: 0,
    emitted: 0,
    pending: 0,
    errors: 0
  };

  const pending = [];

  const nowMs = () => Date.now();

  const noteError = (where) => (error) => {
    counters.errors += 1;
    const message = error && error.message ? String(error.message) : String(error);
    deliverOrQueue({ kind: "error", at_epoch_ms: nowMs(), where: where, message: message.slice(0, 300) });
  };

  function deliver(sink, event) {
    try {
      const result = sink(event);
      if (result && typeof result.catch === "function") {
        result.catch(() => {
          counters.errors += 1;
        });
      }
      counters.emitted += 1;
    } catch (error) {
      counters.errors += 1;
    }
  }

  function flush(sink) {
    while (pending.length) {
      deliver(sink, pending.shift());
    }
    counters.pending = 0;
  }

  function deliverOrQueue(event) {
    const sink = window.__hansardEmit;
    if (typeof sink !== "function") {
      pending.push(event);
      if (pending.length > MAX_PENDING) {
        pending.shift();
      }
      counters.pending = pending.length;
      return;
    }
    if (pending.length) {
      flush(sink);
    }
    deliver(sink, event);
  }

  const emit = deliverOrQueue;

  function tryParseJson(text) {
    if (typeof text !== "string") {
      return null;
    }
    const trimmed = text.trim();
    if (!trimmed || (trimmed[0] !== "{" && trimmed[0] !== "[")) {
      return null;
    }
    try {
      return JSON.parse(trimmed);
    } catch (error) {
      return null;
    }
  }

  function coerceObject(value) {
    if (typeof value === "string") {
      return tryParseJson(value);
    }
    return value && typeof value === "object" ? value : null;
  }

  function base64ToBytes(text) {
    try {
      const binary = atob(text);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      return bytes;
    } catch (error) {
      return null;
    }
  }

  async function inflate(bytes) {
    if (typeof DecompressionStream !== "function") {
      return null;
    }
    const formats = ["deflate", "deflate-raw", "gzip"];
    for (const format of formats) {
      try {
        const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream(format));
        const text = await new Response(stream).text();
        if (text) {
          return text;
        }
      } catch (error) {
        counters.ws_decode_failures += 0;
      }
    }
    return null;
  }

  async function decodeSignallingBody(payload) {
    const direct = tryParseJson(payload);
    if (direct) {
      return direct;
    }
    const bytes = base64ToBytes(payload.trim());
    if (!bytes || !bytes.length) {
      return null;
    }
    const plain = tryParseJson(new TextDecoder("utf-8", { fatal: false }).decode(bytes));
    if (plain) {
      return plain;
    }
    const inflated = await inflate(bytes);
    return inflated ? tryParseJson(inflated) : null;
  }

  function headerValue(headers) {
    for (const name of CHAIN_ID_HEADERS) {
      const value = headers[name];
      if (typeof value === "string" && value) {
        return value;
      }
    }
    return null;
  }

  function collectAudioSources(entry) {
    const sources = [];
    const endpoints = entry.endpoints && typeof entry.endpoints === "object" ? entry.endpoints : {};
    for (const endpointKey of Object.keys(endpoints)) {
      const endpoint = endpoints[endpointKey];
      const call = endpoint && typeof endpoint === "object" ? endpoint.call : null;
      const streams = call && Array.isArray(call.mediaStreams) ? call.mediaStreams : [];
      for (const stream of streams) {
        if (!stream || stream.type !== "audio") {
          continue;
        }
        const sourceId = Number(stream.sourceId);
        if (Number.isFinite(sourceId) && sources.indexOf(sourceId) < 0) {
          sources.push(sourceId);
        }
      }
    }
    return sources;
  }

  function emitRoster(body, callId) {
    const participants = body.participants;
    if (!participants || typeof participants !== "object") {
      return;
    }
    const rows = [];
    for (const key of Object.keys(participants)) {
      const entry = participants[key];
      if (!entry || typeof entry !== "object") {
        continue;
      }
      const details = entry.details && typeof entry.details === "object" ? entry.details : {};
      const displayName = typeof details.displayName === "string" ? details.displayName.trim() : "";
      if (!displayName) {
        continue;
      }
      rows.push({
        id: String(details.id || key),
        display_name: displayName,
        state: typeof entry.state === "string" ? entry.state : "unknown",
        meeting_role: typeof entry.meetingRole === "string" ? entry.meetingRole : null,
        audio_sources: collectAudioSources(entry)
      });
    }
    if (!rows.length) {
      return;
    }
    counters.roster_updates += 1;
    emit({ kind: "roster", at_epoch_ms: nowMs(), call_id: callId, participants: rows });
  }

  function emitCallEnd(body, callId, url) {
    const code = Number(body.code);
    const subCode = Number(body.subCode);
    counters.call_end += 1;
    emit({
      kind: "call_end",
      at_epoch_ms: nowMs(),
      call_id: callId,
      url: url,
      code: Number.isFinite(code) ? code : null,
      sub_code: Number.isFinite(subCode) ? subCode : null,
      reason: typeof body.reason === "string" ? body.reason : null
    });
  }

  function processSignallingEvent(decoded) {
    const events = Array.isArray(decoded) ? decoded : [decoded];
    for (const event of events) {
      if (!event || typeof event !== "object") {
        continue;
      }
      const url = typeof event.url === "string" ? event.url : "";
      const headers = event.headers && typeof event.headers === "object" ? event.headers : {};
      const callId = headerValue(headers);
      const body = coerceObject(event.body !== undefined ? event.body : event);
      if (!body) {
        continue;
      }
      if (url.indexOf("rosterUpdate") >= 0 || body.participants) {
        emitRoster(body, callId);
      }
      const endsCall = url.indexOf("conversationEnd") >= 0 || (body.code !== undefined && body.subCode !== undefined);
      if (endsCall) {
        emitCallEnd(body, callId, url);
      }
    }
  }

  function handleSocketMessage(data) {
    if (typeof data !== "string") {
      if (typeof Blob === "function" && data instanceof Blob) {
        data.text().then(handleSocketMessage).catch(noteError("websocket-blob"));
      } else if (data instanceof ArrayBuffer) {
        handleSocketMessage(new TextDecoder("utf-8", { fatal: false }).decode(new Uint8Array(data)));
      }
      return;
    }
    if (data.indexOf("3:::") !== 0) {
      return;
    }
    counters.ws_frames += 1;
    decodeSignallingBody(data.slice(4))
      .then((decoded) => {
        if (!decoded) {
          counters.ws_decode_failures += 1;
          return;
        }
        processSignallingEvent(decoded);
      })
      .catch(noteError("websocket-decode"));
  }

  function installWebSocketHook() {
    const NativeWebSocket = window.WebSocket;
    if (typeof NativeWebSocket !== "function") {
      return;
    }
    const HookedWebSocket = function (url, protocols) {
      const socket = protocols === undefined ? new NativeWebSocket(url) : new NativeWebSocket(url, protocols);
      try {
        socket.addEventListener("message", (event) => {
          try {
            handleSocketMessage(event.data);
          } catch (error) {
            counters.errors += 1;
          }
        });
      } catch (error) {
        counters.errors += 1;
      }
      return socket;
    };
    HookedWebSocket.prototype = NativeWebSocket.prototype;
    for (const constant of ["CONNECTING", "OPEN", "CLOSING", "CLOSED"]) {
      try {
        HookedWebSocket[constant] = NativeWebSocket[constant];
      } catch (error) {
        counters.errors += 1;
      }
    }
    try {
      Object.defineProperty(window, "WebSocket", {
        configurable: true,
        writable: true,
        value: HookedWebSocket
      });
    } catch (error) {
      noteError("websocket-hook")(error);
    }
  }

  const peerConnections = new Set();
  let lastDominantSource = undefined;

  function handleDataChannelMessage(label, data) {
    if (typeof data !== "string") {
      if (typeof Blob === "function" && data instanceof Blob) {
        data.text().then((text) => handleDataChannelMessage(label, text)).catch(noteError("datachannel-blob"));
      } else if (data instanceof ArrayBuffer) {
        handleDataChannelMessage(label, new TextDecoder("utf-8", { fatal: false }).decode(new Uint8Array(data)));
      }
      return;
    }
    const parsed = tryParseJson(data);
    if (!parsed) {
      return;
    }
    const items = Array.isArray(parsed) ? parsed : [parsed];
    for (const item of items) {
      if (!item || item.type !== "dsh" || !Array.isArray(item.history)) {
        continue;
      }
      counters.dsh_messages += 1;
      const head = Number(item.history[0]);
      const sourceId = Number.isFinite(head) && head > 0 ? head : null;
      if (sourceId === lastDominantSource) {
        continue;
      }
      lastDominantSource = sourceId;
      counters.dsh_transitions += 1;
      emit({
        kind: "dominant",
        at_epoch_ms: nowMs(),
        source_id: sourceId,
        channel_label: label,
        history: item.history.filter((value) => Number.isFinite(Number(value))).map(Number)
      });
    }
  }

  function attachDataChannel(channel) {
    if (!channel || channel.__hansardHooked) {
      return;
    }
    try {
      channel.__hansardHooked = true;
      counters.data_channels += 1;
      channel.addEventListener("message", (event) => {
        try {
          handleDataChannelMessage(channel.label, event.data);
        } catch (error) {
          counters.errors += 1;
        }
      });
    } catch (error) {
      counters.errors += 1;
    }
  }

  function registerPeerConnection(connection) {
    peerConnections.add(connection);
    counters.peer_connections = peerConnections.size;
    try {
      connection.addEventListener("datachannel", (event) => attachDataChannel(event.channel));
      connection.addEventListener("connectionstatechange", () => {
        if (connection.connectionState === "closed") {
          peerConnections.delete(connection);
          counters.peer_connections = peerConnections.size;
        }
      });
    } catch (error) {
      counters.errors += 1;
    }
  }

  function installPeerConnectionHook() {
    const NativePeerConnection = window.RTCPeerConnection;
    if (typeof NativePeerConnection !== "function") {
      return;
    }
    const nativeCreateDataChannel = NativePeerConnection.prototype.createDataChannel;
    if (typeof nativeCreateDataChannel === "function") {
      NativePeerConnection.prototype.createDataChannel = function (label, options) {
        const channel = nativeCreateDataChannel.call(this, label, options);
        attachDataChannel(channel);
        return channel;
      };
    }
    const HookedPeerConnection = function (...args) {
      const connection = new NativePeerConnection(...args);
      registerPeerConnection(connection);
      return connection;
    };
    HookedPeerConnection.prototype = NativePeerConnection.prototype;
    try {
      Object.defineProperty(window, "RTCPeerConnection", {
        configurable: true,
        writable: true,
        value: HookedPeerConnection
      });
      window.webkitRTCPeerConnection = HookedPeerConnection;
    } catch (error) {
      noteError("peerconnection-hook")(error);
    }
  }

  const csrcWindows = new Map();
  const csrcLastSeen = new Map();
  const csrcOwners = new Map();
  let activeCsrc = [];
  let lastOwnerLookup = 0;

  function sameNumbers(left, right) {
    if (left.length !== right.length) {
      return false;
    }
    for (let index = 0; index < left.length; index += 1) {
      if (left[index] !== right[index]) {
        return false;
      }
    }
    return true;
  }

  function sameStrings(left, right) {
    return sameNumbers(left, right);
  }

  function resolveActiveCall() {
    try {
      const handle = window.msteamscalling;
      const resolved = handle && typeof handle.deref === "function" ? handle.deref() : handle;
      const service = resolved && resolved.callingService;
      if (!service || typeof service.getActiveCall !== "function") {
        return null;
      }
      return service.getActiveCall();
    } catch (error) {
      counters.errors += 1;
      return null;
    }
  }

  function participantList(call) {
    const participants = call && call.participants ? call.participants : null;
    if (!participants) {
      return [];
    }
    if (Array.isArray(participants)) {
      return participants;
    }
    if (typeof participants.values === "function") {
      try {
        return Array.from(participants.values());
      } catch (error) {
        counters.errors += 1;
        return [];
      }
    }
    return Object.keys(participants).map((key) => participants[key]);
  }

  function participantIdentity(participant) {
    const details = participant && participant.details ? participant.details : {};
    const candidates = [participant.id, participant.mri, participant.participantId, details.id];
    for (const candidate of candidates) {
      if (typeof candidate === "string" && candidate) {
        return candidate;
      }
    }
    return null;
  }

  function resolveCsrcOwners(sources, at) {
    const unknown = sources.filter((source) => !csrcOwners.has(source));
    if (!unknown.length || at - lastOwnerLookup < OWNER_REFRESH_MS) {
      return;
    }
    lastOwnerLookup = at;
    const call = resolveActiveCall();
    const participants = participantList(call);
    if (!participants.length) {
      return;
    }
    const mapping = {};
    for (const source of unknown) {
      for (const participant of participants) {
        try {
          if (participant && typeof participant.hasAudioSource === "function" && participant.hasAudioSource(source)) {
            const identity = participantIdentity(participant);
            if (identity) {
              csrcOwners.set(source, identity);
              mapping[String(source)] = identity;
            }
            break;
          }
        } catch (error) {
          counters.errors += 1;
        }
      }
    }
    const resolved = Object.keys(mapping);
    if (!resolved.length) {
      return;
    }
    counters.csrc_mapped += resolved.length;
    emit({ kind: "csrc_map", at_epoch_ms: at, mapping: mapping });
  }

  function collectRecentCsrc(at) {
    const seen = new Set();
    for (const connection of Array.from(peerConnections)) {
      let receivers = [];
      try {
        receivers = typeof connection.getReceivers === "function" ? connection.getReceivers() : [];
      } catch (error) {
        counters.errors += 1;
        continue;
      }
      for (const receiver of receivers) {
        const track = receiver && receiver.track;
        if (!track || track.kind !== "audio") {
          continue;
        }
        let contributions = [];
        try {
          contributions =
            typeof receiver.getContributingSources === "function" ? receiver.getContributingSources() : [];
        } catch (error) {
          counters.errors += 1;
          continue;
        }
        for (const contribution of contributions) {
          if (!contribution) {
            continue;
          }
          const age = performance.now() - Number(contribution.timestamp);
          if (!Number.isFinite(age) || age > CSRC_RECENCY_MS || age < -CSRC_RECENCY_MS) {
            continue;
          }
          const source = Number(contribution.source);
          if (!Number.isFinite(source)) {
            continue;
          }
          seen.add(source);
          csrcLastSeen.set(source, at);
        }
      }
    }
    return seen;
  }

  function pollContributingSources() {
    const at = nowMs();
    counters.csrc_polls += 1;
    const seen = collectRecentCsrc(at);
    const known = new Set();
    csrcWindows.forEach((value, key) => known.add(key));
    seen.forEach((key) => known.add(key));
    const next = [];
    known.forEach((source) => {
      const history = csrcWindows.get(source) || [];
      history.push(seen.has(source) ? 1 : 0);
      while (history.length > CSRC_WINDOW) {
        history.shift();
      }
      csrcWindows.set(source, history);
      const hits = history.reduce((total, value) => total + value, 0);
      const held = at - (csrcLastSeen.get(source) || 0) <= CSRC_HOLD_MS;
      const wasActive = activeCsrc.indexOf(source) >= 0;
      if (held && (wasActive || hits >= CSRC_MIN_HITS)) {
        next.push(source);
      } else if (!held && hits === 0) {
        csrcWindows.delete(source);
        csrcLastSeen.delete(source);
      }
    });
    next.sort((left, right) => left - right);
    if (!sameNumbers(next, activeCsrc)) {
      activeCsrc = next;
      counters.csrc_transitions += 1;
      emit({ kind: "csrc", at_epoch_ms: at, sources: next.slice() });
    }
    if (next.length) {
      resolveCsrcOwners(next, at);
    }
  }

  let lastDomSpeakers = [];
  let lastDomRoster = [];

  function readDomSpeakers() {
    const names = [];
    let nodes = [];
    try {
      nodes = Array.from(document.querySelectorAll(SPEAKING_INDICATOR));
    } catch (error) {
      counters.errors += 1;
      return names;
    }
    for (const node of nodes) {
      const container = typeof node.closest === "function" ? node.closest(SPEAKING_CONTAINER) : null;
      const name = container ? (container.getAttribute("data-tid") || "").trim() : "";
      if (name && names.indexOf(name) < 0) {
        names.push(name);
      }
    }
    names.sort();
    return names;
  }

  function readDomRoster() {
    const names = [];
    let panels = [];
    try {
      panels = Array.from(document.querySelectorAll(ROSTER_PANEL));
    } catch (error) {
      counters.errors += 1;
      return names;
    }
    for (const panel of panels) {
      let rows = [];
      try {
        rows = Array.from(panel.querySelectorAll(ROSTER_ROW));
      } catch (error) {
        counters.errors += 1;
        continue;
      }
      for (const row of rows) {
        const label = (row.getAttribute("aria-label") || row.textContent || "").trim().split("\n")[0].trim();
        if (label && names.indexOf(label) < 0) {
          names.push(label);
        }
      }
    }
    names.sort();
    return names;
  }

  function pollDom() {
    const at = nowMs();
    const speakers = readDomSpeakers();
    if (!sameStrings(speakers, lastDomSpeakers)) {
      lastDomSpeakers = speakers;
      counters.dom_transitions += 1;
      emit({ kind: "dom_speaking", at_epoch_ms: at, display_names: speakers.slice() });
    }
    const roster = readDomRoster();
    if (!sameStrings(roster, lastDomRoster)) {
      lastDomRoster = roster;
      counters.dom_roster_updates += 1;
      emit({ kind: "dom_roster", at_epoch_ms: at, display_names: roster.slice() });
    }
  }

  function snapshot() {
    return {
      counters: Object.assign({}, counters),
      active_csrc: activeCsrc.slice(),
      dominant_source: lastDominantSource === undefined ? null : lastDominantSource,
      mapped_csrc: csrcOwners.size,
      peer_connections: peerConnections.size
    };
  }

  function emitHealth() {
    const state = snapshot();
    emit({
      kind: "health",
      at_epoch_ms: nowMs(),
      counters: state.counters,
      active_csrc: state.active_csrc,
      dominant_source: state.dominant_source,
      mapped_csrc: state.mapped_csrc,
      peer_connections: state.peer_connections
    });
  }

  function guarded(name, callback) {
    return () => {
      try {
        callback();
      } catch (error) {
        noteError(name)(error);
      }
    };
  }

  installWebSocketHook();
  installPeerConnectionHook();

  window.__hansardCounters = counters;
  window.__hansardSnapshot = snapshot;

  setInterval(guarded("csrc-poll", pollContributingSources), CSRC_POLL_MS);
  setInterval(guarded("dom-poll", pollDom), DOM_POLL_MS);
  setInterval(guarded("health", emitHealth), HEALTH_INTERVAL_MS);
  setInterval(
    guarded("flush", () => {
      const sink = window.__hansardEmit;
      if (typeof sink === "function" && pending.length) {
        flush(sink);
      }
    }),
    FLUSH_INTERVAL_MS
  );

  emit({ kind: "ready", at_epoch_ms: nowMs(), href: String(window.location && window.location.href) });
})();
