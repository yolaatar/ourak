const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

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

export function login(password) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export function logout() {
  return request("/auth/logout");
}

export function generateTopics(description, seedAbstracts) {
  return request("/onboarding/generate-topics", {
    method: "POST",
    body: JSON.stringify({ description, seed_abstracts: seedAbstracts }),
  });
}

export async function runFirstPass(topics, userEmail, userName, onProgress, seedAbstracts = []) {
  const res = await fetch(`${BASE}/onboarding/run-first-pass`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topics, user_email: userEmail, user_name: userName, seed_abstracts: seedAbstracts }),
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

    // Parse SSE lines
    const lines = buffer.split("\n\n");
    buffer = lines.pop(); // keep incomplete chunk
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

export function completeOnboarding(userName, userEmail, topics, feedback) {
  return request("/onboarding/complete", {
    method: "POST",
    body: JSON.stringify({
      user_name: userName,
      user_email: userEmail,
      topics,
      feedback,
    }),
  });
}

export function getPapers({ userId, topicId, sortBy = "score", source, limit = 20, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  if (topicId) params.set("topic_id", topicId);
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

export function getTopics() {
  return request("/topics");
}

export function getUser(userId) {
  return request(`/users/${userId}`);
}
