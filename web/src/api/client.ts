import type { Project, Topic, TopicStatus, Message, PromptResponse } from './types';

const BASE = '';

async function jget<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { cache: 'no-store' });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

async function jpost<T>(path: string, body: object): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

async function jpatch<T>(path: string, body: object): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

async function jdel(path: string): Promise<void> {
  const res = await fetch(BASE + path, { method: 'DELETE' });
  if (!res.ok && res.status !== 204) throw new ApiError(res.status, await res.text());
}

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`API ${status}: ${body}`);
    this.status = status;
    this.body = body;
  }
  /** Best-effort JSON parse of the error body. */
  json(): { error?: string; [k: string]: unknown } | null {
    try { return JSON.parse(this.body); } catch { return null; }
  }
}

export const api = {
  // Projects
  listProjects: () => jget<Project[]>('/projects'),
  createProject: (body: { workspace: string; name?: string; github_url?: string }) =>
    jpost<Project>('/projects', body),
  createProjectFromGithub: (body: { github_url: string; target_dir?: string; name?: string }) =>
    jpost<Project>('/projects/from-github', body),
  getProject: (id: string) =>
    jget<{ project: Project; topics: Topic[] }>(`/projects/${encodeURIComponent(id)}`),
  updateProject: (id: string, body: Partial<Project>) =>
    jpatch<Project>(`/projects/${encodeURIComponent(id)}`, body),
  deleteProject: (id: string) => jdel(`/projects/${encodeURIComponent(id)}`),
  openProject: (id: string) => jpost<Project>(`/projects/${encodeURIComponent(id)}/open`, {}),
  recents: () => jget<Project[]>('/recents'),

  // Topics
  listTopics: (projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    return jget<Topic[]>(`/topics${q}`);
  },
  createTopic: (body: { name: string; project_id: string; workspace?: string }) =>
    jpost<{ name: string; url: string }>('/topic', body),

  // Iteration
  getStatus: (topic: string) =>
    jget<TopicStatus>(`/status/${encodeURIComponent(topic)}`),
  sendPrompt: (body: { topic: string; content: string; workspace?: string }) =>
    jpost<PromptResponse>('/prompt', body),

  // Transcript (JSONL fetched directly, not JSON)
  fetchTranscript: async (topic: string): Promise<Message[]> => {
    const res = await fetch(`/${encodeURIComponent(topic)}.jsonl?t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) return [];
    const text = await res.text();
    const out: Message[] = [];
    for (const line of text.split('\n')) {
      if (!line.trim()) continue;
      try { out.push(JSON.parse(line)); } catch { /* skip malformed */ }
    }
    return out;
  },
};
