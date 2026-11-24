"use client";

import { RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks";

type H = { status: string; checks: Record<string, Record<string, string | number | null>>; modules: { key: string; version: string; platform_state: string }[] };
type DL = { id: string; event_type: string; attempts: number; last_error: string | null; occurred_at: string };

export default function Health() {
  const toast = useToast();
  const h = useQuery<H>("/platform/health");
  const dl = useQuery<DL[]>("/platform/dead-letters");
  if (h.loading && !h.data) return <Loading />;
  if (h.error) return <ErrorState error={h.error} onRetry={h.reload} />;
  return (
    <>
      <PageHeader title={<span className="flex items-center gap-2">System health <StatusBadge status={h.data!.status} /></span>} crumbs={[{ label: "Platform" }, { label: "Health" }]}
        actions={<Button variant="secondary" onClick={() => { h.reload(); dl.reload(); }}><RefreshCw className="h-4 w-4" />Refresh</Button>} />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {Object.entries(h.data!.checks).map(([k, c]) => (
          <Card key={k} className="p-4">
            <div className="flex items-center justify-between"><p className="font-medium capitalize">{k}</p><StatusBadge status={String(c.status)} /></div>
            <dl className="mt-2 space-y-0.5 text-xs text-muted">
              {Object.entries(c).filter(([x]) => x !== "status").map(([x, v]) => <div key={x} className="flex justify-between"><dt>{x.replace(/_/g, " ")}</dt><dd>{String(v ?? "—")}</dd></div>)}
            </dl>
          </Card>
        ))}
      </div>
      <Card className="mt-6">
        <CardHeader title="Dead-lettered events" subtitle="Outbox events that failed 5 times. Replaying is safe: consumers are idempotent." />
        {!dl.data?.length ? <p className="px-5 py-4 text-sm text-muted">No dead letters.</p> : (
          <ul className="divide-y divide-line text-sm">
            {dl.data.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5">
                <span><code>{e.event_type}</code> <span className="text-xs text-muted">· {dateTime(e.occurred_at)} · {e.attempts} attempts · {e.last_error}</span></span>
                <Button size="sm" variant="secondary" onClick={async () => { await api.post(`/platform/dead-letters/${e.id}:replay`); toast.success("Queued for replay"); dl.reload(); }}>Replay</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="mt-6">
        <CardHeader title="Deployed modules" />
        <ul className="grid grid-cols-2 gap-px bg-line text-sm md:grid-cols-5">
          {h.data!.modules.map((m) => <li key={m.key} className="bg-white px-4 py-2"><p className="font-medium">{m.key}</p><p className="text-xs text-muted">v{m.version} · {m.platform_state}</p></li>)}
        </ul>
      </Card>
    </>
  );
}
