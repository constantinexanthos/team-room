import { useEffect, useState } from 'react';
import { api } from '@/api/client';
import type { Project } from '@/api/types';
import { ProjectPicker } from '@/components/ProjectPicker';
import { ProjectView } from '@/components/ProjectView';

const LAST_PROJECT_KEY = 'team-room:last-project-id';

export default function App() {
  const [openProject, setOpenProject] = useState<Project | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [booting, setBooting] = useState(true);

  // Boot: try to auto-open the most-recently-active project. If the user
  // explicitly went back to picker (via close), don't auto-resume — they
  // want to pick again.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const recents = await api.recents();
        if (cancelled) return;
        const lastId = localStorage.getItem(LAST_PROJECT_KEY);
        const target =
          (lastId && recents.find((p) => p.id === lastId)) ||
          recents[0] ||
          null;
        if (target) {
          // Bump last_opened_at so the resume sticks
          const opened = await api.openProject(target.id);
          if (cancelled) return;
          localStorage.setItem(LAST_PROJECT_KEY, opened.id);
          setOpenProject(opened);
        } else {
          setShowPicker(true);
        }
      } catch (e) {
        if (cancelled) return;
        setBootError(String(e));
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function handleOpen(project: Project) {
    localStorage.setItem(LAST_PROJECT_KEY, project.id);
    setOpenProject(project);
    setShowPicker(false);
  }

  function handleClose() {
    // Explicit close → user wants the picker. Clear last so we don't bounce
    // back into the same project on next launch.
    localStorage.removeItem(LAST_PROJECT_KEY);
    setOpenProject(null);
    setShowPicker(true);
  }

  if (bootError) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-md rounded-md border border-[var(--color-border)] bg-[var(--color-bg-2)] p-6 text-sm">
          <div className="mb-2 font-semibold text-[var(--color-danger)]">Backend unreachable</div>
          <div className="text-[var(--color-muted)]">{bootError}</div>
          <div className="mt-4 text-xs text-[var(--color-muted)]">
            The Python server must be running. Try{' '}
            <code className="rounded bg-[var(--color-bg-3)] px-1 py-0.5">./start.sh</code> in the team-room repo.
          </div>
        </div>
      </div>
    );
  }

  if (booting) {
    return <div className="flex h-full items-center justify-center text-[var(--color-muted)] text-xs uppercase tracking-widest">Loading…</div>;
  }

  if (openProject && !showPicker) {
    return <ProjectView project={openProject} onClose={handleClose} />;
  }

  return <ProjectPicker onOpen={handleOpen} />;
}
