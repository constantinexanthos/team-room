import { useEffect, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Project } from '@/api/types';
import { cx, formatRelative, tildify } from '@/lib/utils';
import { NewProjectModal } from './NewProjectModal';
import { Brand } from './Brand';

interface Props {
  onOpen: (project: Project) => void;
}

type ModalMode = 'folder' | 'github' | null;

export function ProjectPicker({ onOpen }: Props) {
  const [recents, setRecents] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalMode>(null);
  const [quickStarting, setQuickStarting] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .recents()
      .then((items) => {
        if (!alive) return;
        setRecents(items);
        setLoading(false);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e instanceof ApiError ? e.message : String(e));
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  async function handleQuickStart() {
    setError(null);
    setQuickStarting(true);
    try {
      const home = (window as { __HOME__?: string }).__HOME__ || '';
      // Server resolves the default workspace; send empty/home as a sensible hint.
      const project = await api.createProject({ workspace: home });
      onOpen(project);
    } catch (err) {
      if (err instanceof ApiError) {
        const parsed = err.json();
        setError(parsed?.error ? String(parsed.error) : err.message);
      } else {
        setError(String(err));
      }
      setQuickStarting(false);
    }
  }

  async function handleOpenRecent(p: Project) {
    setError(null);
    try {
      const project = await api.openProject(p.id);
      onOpen(project);
    } catch (err) {
      if (err instanceof ApiError) {
        const parsed = err.json();
        setError(parsed?.error ? String(parsed.error) : err.message);
      } else {
        setError(String(err));
      }
    }
  }

  return (
    <div className="brand-wash flex h-full items-start justify-center overflow-y-auto px-4 pt-[14vh] pb-12">
      <div className="w-full max-w-[520px]">
        {/* Brand lockup */}
        <header className="mb-10 flex flex-col items-center gap-3.5">
          <div className="brand-rise">
            <Brand variant="mark" size={32} />
          </div>
          <div className="brand-rise-delay-1">
            <Brand variant="wordmark" />
          </div>
          <p className="brand-rise-delay-2 text-center text-[12px] text-[var(--color-muted)]">
            Two minds, one room.
          </p>
        </header>

        <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-2)]/90 shadow-[0_1px_0_0_rgba(255,255,255,0.02)_inset]">
          <PickerRow
            icon={<FolderIcon />}
            label="Open project"
            description="Point at a workspace folder on disk"
            onClick={() => setModal('folder')}
          />
          <Divider />
          <PickerRow
            icon={<GlobeIcon />}
            label="Open GitHub project"
            description="Paste a GitHub URL and pick a local clone"
            onClick={() => setModal('github')}
          />
          <Divider />
          <PickerRow
            icon={<PlusIcon />}
            label="Quick start"
            description="Open a scratch project in your home directory"
            onClick={() => void handleQuickStart()}
            disabled={quickStarting}
            trailing={quickStarting ? <span className="text-xs text-[var(--color-muted)]">Opening...</span> : null}
          />
        </div>

        {error && (
          <div className="mt-4 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-3 py-2 text-xs text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <section className="mt-10">
          <div className="mb-2.5 flex items-center justify-between px-1">
            <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[var(--color-muted)]">
              Recents
            </div>
            {recents.length > 0 && (
              <div className="font-mono text-[10px] text-[var(--color-muted)]/70">
                {recents.length}
              </div>
            )}
          </div>
          {loading ? (
            <div className="px-1 text-xs text-[var(--color-muted)]">Loading...</div>
          ) : recents.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--color-border)] px-4 py-6 text-center text-xs text-[var(--color-muted)]">
              No recent projects yet. Open one above to get started.
            </div>
          ) : (
            <ul className="divide-y divide-[var(--color-border)] overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-2)]/90">
              {recents.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => void handleOpenRecent(p)}
                    className="recent-row group flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-[var(--color-bg-3)]"
                  >
                    <span className="text-[var(--color-muted)] transition-colors group-hover:text-[var(--color-claude)]">
                      <FolderIcon />
                    </span>
                    <span className="flex-1 truncate">
                      <span className="block truncate text-[13px] font-medium text-[var(--color-text)]">
                        {p.name}
                      </span>
                      <span className="block truncate font-mono text-[11px] text-[var(--color-muted)]">
                        {tildify(p.workspace)}
                      </span>
                    </span>
                    {p.last_opened_at && (
                      <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
                        {formatRelative(p.last_opened_at)}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {modal && (
        <NewProjectModal
          mode={modal}
          onClose={() => setModal(null)}
          onCreated={(project) => {
            setModal(null);
            onOpen(project);
          }}
        />
      )}
    </div>
  );
}

interface RowProps {
  icon: React.ReactNode;
  label: string;
  description?: string;
  onClick: () => void;
  disabled?: boolean;
  trailing?: React.ReactNode;
}

function PickerRow({ icon, label, description, onClick, disabled, trailing }: RowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cx(
        'picker-row group flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors',
        'hover:bg-[var(--color-bg-3)] disabled:cursor-not-allowed disabled:opacity-50',
      )}
    >
      <span className="text-[var(--color-muted)] transition-colors group-hover:text-[var(--color-costa)]">
        {icon}
      </span>
      <span className="flex-1">
        <span className="block text-[13px] font-medium text-[var(--color-text)]">{label}</span>
        {description && (
          <span className="block text-[11px] text-[var(--color-muted)]">{description}</span>
        )}
      </span>
      {trailing ?? <ChevronRightIcon />}
    </button>
  );
}

function Divider() {
  return <div className="h-px bg-[var(--color-border)]" />;
}

function FolderIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
    </svg>
  );
}

function GlobeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function ChevronRightIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--color-muted)] transition-transform group-hover:translate-x-0.5" aria-hidden="true">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}
