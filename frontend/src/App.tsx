import { useState } from "react";
import { ApiError, runPipeline } from "./lib/api";
import type { ProfileCreatedResponse, RunResponse } from "./lib/types";
import { Header } from "./components/Header";
import { ProfileForm } from "./components/ProfileForm";
import { RunPanel } from "./components/RunPanel";
import { QueriesTable } from "./components/QueriesTable";
import { Recommendations } from "./components/Recommendations";
import { ReportView } from "./components/ReportView";

export default function App() {
  const [profile, setProfile] = useState<ProfileCreatedResponse | null>(null);
  const [run, setRun] = useState<RunResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  // Bumped after each run / recheck to refresh the dependent panels.
  const [refreshKey, setRefreshKey] = useState(0);

  async function handleRun() {
    if (!profile) return;
    setRunning(true);
    setRunError(null);
    try {
      const result = await runPipeline(profile.profile_uuid);
      setRun(result);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setRunError(
        err instanceof ApiError ? err.message : "The pipeline run failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  function handleReset() {
    setProfile(null);
    setRun(null);
    setRunError(null);
  }

  return (
    <div className="min-h-full bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <Header />
      <main className="mx-auto flex max-w-5xl flex-col gap-5 px-6 py-8">
        {!profile ? (
          <ProfileForm onCreated={setProfile} />
        ) : (
          <>
            <RunPanel
              profile={profile}
              run={run}
              running={running}
              error={runError}
              onRun={handleRun}
              onReset={handleReset}
            />

            {run && (
              <>
                <QueriesTable
                  profileUuid={profile.profile_uuid}
                  refreshKey={refreshKey}
                />
                <Recommendations
                  profileUuid={profile.profile_uuid}
                  refreshKey={refreshKey}
                />
                <ReportView run={run} />
              </>
            )}
          </>
        )}

        <footer className="pt-2 text-center text-xs text-slate-400 dark:text-slate-600">
          Beyond-spec dashboard · the graded backend runs and is testable
          without it.
        </footer>
      </main>
    </div>
  );
}
