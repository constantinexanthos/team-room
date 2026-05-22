export type AgentRole = 'claude' | 'codex' | 'costa' | 'system';

export interface Message {
  ts: string;
  role: AgentRole;
  model: string;
  content: string;
  round?: 1 | 2;
  prompt_id?: string;
}

export interface Project {
  id: string;
  name: string;
  workspace: string;
  github_url: string | null;
  created_at: string;
  last_opened_at: string;
  topic_count?: number;
}

export interface Topic {
  id: string;
  project_id: string;
  created_at: string;
  last_message_at?: string;
  last_role?: AgentRole;
  message_count?: number;
  status?: TopicStatus['status'];
}

export interface TopicStatus {
  status: 'idle' | 'round-1' | 'round-2' | 'crashed';
  prompt_id: string | null;
  started_at: string | null;
  orchestrator_pid: number | null;
  claude_done: boolean;
  codex_done: boolean;
  last_error: string | null;
}

export interface PromptResponse {
  prompt_id: string;
  warning?: string;
  recovered_from_crash?: boolean;
}
