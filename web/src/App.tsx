import { useEffect, useState } from 'react';
import { api } from '@/api/client';
import type { Project } from '@/api/types';
import { ProjectPicker } from '@/components/ProjectPicker';
import { ProjectView } from '@/components/ProjectView';

export default function App() {
  const [openProject, setOpenProject] = useState<Project | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);

  useEffect(() => {
    // Boot probe: server reachable?
    void api.recents().catch((e) => setBootError(String(e)));
  }, []);

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

  if (!openProject) {
    return <ProjectPicker onOpen={setOpenProject} />;
  }

  return <ProjectView project={openProject} onClose={() => setOpenProject(null)} />;
}
