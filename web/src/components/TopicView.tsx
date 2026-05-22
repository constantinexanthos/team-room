import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Message, Project, Topic, TopicStatus } from '@/api/types';
import { useTranscript } from '@/hooks/useTranscript';
import { useStatus } from '@/hooks/useStatus';
import { shortPromptId } from '@/lib/utils';
import { MessageBubble } from './MessageBubble';
import { ThinkingBubble } from './ThinkingBubble';
import { InputDock } from './InputDock';

interface Props {
  topic: Topic;
  project: Project;
}

export function TopicView({ topic, project }: Props) {
  const { messages, error: transcriptError } = useTranscript(topic.id);
  const status = useStatus(topic.id);
  const [toast, setToast] = useState<{ kind: 'error' | 'info'; text: string } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastCountRef = useRef(0);

  // Auto-scroll to bottom on new messages.
  useEffect(() => {
    if (messages.length > lastCountRef.current) {
      lastCountRef.current = messages.length;
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;
      });
    } else if (messages.length < lastCountRef.current) {
      lastCountRef.current = messages.length;
    }
  }, [messages.length]);

  const sendPrompt = useCallback(
    async (text: string) => {
      try {
        await api.sendPrompt({
          topic: topic.id,
          content: text,
          workspace: project.workspace,
        });
      } catch (e) {
        let msg = 'Failed to send. Try again.';
        if (e instanceof ApiError) {
          const body = e.json();
          if (e.status === 409) {
            msg = body?.error
              ? `${body.error}`
              : 'An iteration is already in progress. Wait for it to finish.';
          } else if (body?.error) {
            msg = String(body.error);
          } else {
            msg = `HTTP ${e.status}`;
          }
        }
        setToast({ kind: 'error', text: msg });
        throw e;
      }
    },
    [topic.id, project.workspace],
  );

  useEffect(() => {
    if (transcriptError) setToast({ kind: 'error', text: transcriptError });
  }, [transcriptError]);

  // Toast auto-dismiss
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(id);
  }, [toast]);

  const groups = useMemo(() => groupByPromptId(messages), [messages]);

  const isBusy =
    status.status === 'round-1' ||
    status.status === 'round-2' ||
    status.status === 'dialogue';
  const lockReason = (() => {
    if (!isBusy) return undefined;
    if (status.status === 'dialogue') {
      const who = status.current_agent
        ? status.current_agent[0].toUpperCase() + status.current_agent.slice(1)
        : 'Agent';
      const turn = status.turn ?? 1;
      const max = status.max_turns ?? 8;
      return `Live · Turn ${turn}/${max} · ${who} thinking…`;
    }
    if (status.status === 'round-1') return 'Both agents thinking…';
    return 'Agents reading each other…';
  })();

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col bg-[var(--color-bg)]">
      <div ref={scrollRef} className="relative flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[860px] space-y-3 px-6 py-8">
          {groups.length === 0 ? (
            <EmptyState />
          ) : (
            groups.map((g, i) => (
              <IterationGroup
                key={`${g.promptId ?? 'leg'}-${i}`}
                promptId={g.promptId}
                showSeparator={i > 0 || !!g.promptId}
                messages={g.messages}
              />
            ))
          )}

          {/* In-flight skeleton bubbles */}
          {isBusy && <InFlightSkeletons status={status} />}
        </div>

        {toast && (
          <Toast kind={toast.kind} text={toast.text} onDismiss={() => setToast(null)} />
        )}
      </div>

      <InputDock locked={isBusy} lockReason={lockReason} onSend={sendPrompt} />
    </div>
  );
}

/* ---------------------------- Helpers ---------------------------- */

interface Group {
  promptId: string | undefined;
  messages: Message[];
}

function groupByPromptId(messages: Message[]): Group[] {
  const out: Group[] = [];
  let current: Group | null = null;
  for (const m of messages) {
    const pid = m.prompt_id;
    if (pid) {
      if (!current || current.promptId !== pid) {
        current = { promptId: pid, messages: [] };
        out.push(current);
      }
      current.messages.push(m);
    } else {
      if (!current || current.promptId !== undefined) {
        current = { promptId: undefined, messages: [] };
        out.push(current);
      }
      current.messages.push(m);
    }
  }
  return out;
}

function IterationGroup({
  promptId,
  showSeparator,
  messages,
}: {
  promptId: string | undefined;
  showSeparator: boolean;
  messages: Message[];
}) {
  return (
    <>
      {showSeparator && promptId && (
        <div className="flex items-center gap-3 pt-6 pb-2 text-[11px] uppercase tracking-widest text-[var(--color-muted)]">
          <span className="h-px flex-1 bg-[var(--color-border)]" />
          <span>exchange {shortPromptId(promptId)}</span>
          <span className="h-px flex-1 bg-[var(--color-border)]" />
        </div>
      )}
      {messages.map((m, i) => (
        <MessageBubble key={`${m.ts}-${m.role}-${i}`} message={m} />
      ))}
    </>
  );
}

function InFlightSkeletons({ status }: { status: TopicStatus }) {
  // Live dialogue mode: only the current_agent is thinking. The other is
  // waiting their turn. Show a single skeleton so it reads as one continuous
  // back-and-forth, not parallel essays.
  if (status.status === 'dialogue') {
    const who = status.current_agent;
    if (!who) return null;
    return <ThinkingBubble role={who} />;
  }
  // Legacy rounds mode: pair of skeletons, one disappears when its agent
  // is done in the current round.
  const skeletons: Array<'claude' | 'codex'> = [];
  if (!status.claude_done) skeletons.push('claude');
  if (!status.codex_done) skeletons.push('codex');
  if (skeletons.length === 0) return null;
  return (
    <>
      {skeletons.map((role) => (
        <ThinkingBubble key={role} role={role} />
      ))}
    </>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-3 py-24 text-center text-[var(--color-muted)]">
      <div className="text-[13px]">No messages yet — type below to start the conversation.</div>
      <div className="text-[11px]">
        Both agents will read your message, respond cold in parallel, then critique each other.
      </div>
    </div>
  );
}

function Toast({ kind, text, onDismiss }: { kind: 'error' | 'info'; text: string; onDismiss: () => void }) {
  const accent = kind === 'error' ? 'border-l-[var(--color-danger)]' : 'border-l-[var(--color-costa)]';
  return (
    <div className="fixed left-1/2 top-20 z-50 -translate-x-1/2">
      <div className={`flex items-center gap-3 rounded-md border border-[var(--color-border)] border-l-[3px] bg-[var(--color-bg-2)] px-4 py-3 text-[12px] shadow-lg ${accent}`}>
        <span className="max-w-md">{text}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="text-[var(--color-muted)] hover:text-[var(--color-text)]"
          aria-label="dismiss"
        >
          ×
        </button>
      </div>
    </div>
  );
}
