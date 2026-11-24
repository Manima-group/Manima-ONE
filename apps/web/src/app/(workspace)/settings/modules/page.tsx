"use client";

import { useState } from "react";
import { FormDialog } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Mod = { key: string; name: string; description: string; depends_on: string[]; state: string; entitled: boolean; platform_state: string; writable: boolean; reason: string | null };

export default function Modules() {
  const toast = useToast();
  const { refresh } = useSession();
  const { data, error, loading, reload } = useQuery<Mod[]>("/tenant/modules");
  const [target, setTarget] = useState<{ mod: Mod; state: string } | null>(null);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const names = Object.fromEntries(data!.map((m) => [m.key, m.name]));
  return (
    <>
      <PageHeader title="Modules" crumbs={[{ label: "Settings" }, { label: "Modules" }]}
        subtitle="Switching a module off never deletes data: read-only and disabled modules stay readable and exportable." />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {data!.map((m) => (
          <Card key={m.key} className="p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium">{m.name}</p>
                <p className="text-sm text-muted">{m.description}</p>
              </div>
              <StatusBadge status={m.state} />
            </div>
            {m.depends_on.length > 0 && <p className="mt-2 text-xs text-muted">Requires: {m.depends_on.map((d) => names[d] ?? d).join(", ")}</p>}
            {!m.entitled && <p className="mt-2"><Badge tone="orange">Not in your plan</Badge></p>}
            <div className="mt-3 flex flex-wrap gap-2">
              {m.state !== "enabled" && m.entitled && <Button size="sm" onClick={() => setTarget({ mod: m, state: "enabled" })}>Enable</Button>}
              {m.state === "enabled" && <Button size="sm" variant="secondary" onClick={() => setTarget({ mod: m, state: "read_only" })}>Make read-only</Button>}
              {["enabled", "read_only", "draining"].includes(m.state) && <Button size="sm" variant="ghost" onClick={() => setTarget({ mod: m, state: "disabled" })}>Disable</Button>}
            </div>
          </Card>
        ))}
      </div>
      <FormDialog open={!!target} onClose={() => setTarget(null)} title={`${target?.state === "enabled" ? "Enable" : target?.state === "disabled" ? "Disable" : "Make read-only"}: ${target?.mod.name ?? ""}`}
        submitLabel="Confirm" fields={[{ name: "reason", label: "Reason (recorded in the audit log)", required: true, type: "textarea" }]} initial={{}}
        submit={async (v) => { await api.patch(`/tenant/modules/${target!.mod.key}`, { state: target!.state, reason: v.reason }); toast.success("Module updated"); reload(); refresh(); }} />
    </>
  );
}
