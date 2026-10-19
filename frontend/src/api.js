const BASE = import.meta.env.VITE_API_URL ?? "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (res.status === 401 && !path.startsWith("/auth")) {
    window.location.href = "/login";
    return;
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// --- Auth ---

export function login(username, password) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return request("/auth/logout");
}

export function getMe() {
  return request("/auth/me");
}

// --- Profiles ---

export function getProfiles() {
  return request("/profiles");
}

export function deleteProfile(profileId) {
  return request(`/profiles/${profileId}`, { method: "DELETE" });
}

export function renameProfile(profileId, name) {
  return request(`/profiles/${profileId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

// --- Presets ---

export function getPresets() {
  return request("/onboarding/presets");
}

export function createPreset(data) {
  return request("/onboarding/presets", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function deletePreset(presetId) {
  return request(`/onboarding/presets/${presetId}`, { method: "DELETE" });
}

// --- Onboarding ---

export function generateTopics(description, seedAbstracts) {
  return request("/onboarding/generate-topics", {
    method: "POST",
    body: JSON.stringify({ description, seed_abstracts: seedAbstracts }),
  });
}

export async function runFirstPass(topics, userName, onProgress, seedAbstracts = [], description = "") {
  const res = await fetch(`${BASE}/onboarding/run-first-pass`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topics, user_name: userName, seed_abstracts: seedAbstracts, description }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n\n");
    buffer = lines.pop();
    for (const line of lines) {
      const match = line.match(/^data: (.+)$/m);
      if (!match) continue;
      const event = JSON.parse(match[1]);
      if (event.type === "progress" && onProgress) {
        onProgress(event);
      } else if (event.type === "results") {
        result = event;
      }
    }
  }

  return result;
}

export async function refreshProfile(profileId, onProgress) {
  const res = await fetch(`${BASE}/profiles/${profileId}/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Refresh failed");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop();
    for (const line of lines) {
      const match = line.match(/^data: (.+)$/m);
      if (!match) continue;
      const event = JSON.parse(match[1]);
      if (event.type === "progress" && onProgress) onProgress(event);
      else if (event.type === "done") result = event;
    }
  }
  return result;
}

export function completeOnboarding(userName, topics, feedback, profileName = "") {
  return request("/onboarding/complete", {
    method: "POST",
    body: JSON.stringify({
      user_name: userName,
      profile_name: profileName,
      topics,
      feedback,
    }),
  });
}

// --- Papers ---

export function getPapers({ userId, topicId, profileId, sortBy = "score", source, limit = 20, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  if (topicId) params.set("topic_id", topicId);
  if (profileId) params.set("profile_id", profileId);
  if (sortBy) params.set("sort_by", sortBy);
  if (source) params.set("source", source);
  params.set("limit", limit);
  params.set("offset", offset);
  return request(`/papers?${params}`);
}

export function submitFeedback(paperId, userId, signal) {
  return request(`/papers/${paperId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, signal }),
  });
}

// --- Topics ---

export function getTopics(profileId) {
  const params = new URLSearchParams();
  if (profileId) params.set("profile_id", profileId);
  return request(`/topics?${params}`);
}

export function getUser(userId) {
  return request(`/users/${userId}`);
}
