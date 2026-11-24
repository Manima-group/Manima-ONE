"use client";

import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { Badge, Button, Dialog } from "@/components/ui";
import { dateTime, label } from "@/lib/format";

type A = { id: string; actor_email: string | null; actor_type: string; action: string; resource_type: string; resource_id: string | null; before: unknown; after: unknown; occurred_at: string };

export function AuditTable({ endpoint }: { endpoint: string }) {
  const [view, setView] = useState<A | null>(null);
  return (
    <>
      <DataTable<A> endpoint={endpoint} searchPlaceholder="Search action or user"
        filters={[{ key: "resource_type", label: "Resource", options: ["lead", "account", "quotation", "sales_order", "invoice", "payment", "item", "module", "role", "membership", "tenant", "plan", "subscription"].map((v) => ({ value: v, label: label(v) })) }]}
        columns={[
          { key: "occurred_at", header: "When", render: (r) => dateTime(r.occurred_at) },
          { key: "actor_email", header: "Actor", render: (r) => r.actor_email ?? <Badge>{r.actor_type}</Badge> },
          { key: "action", header: "Action", render: (r) => <code className="text-xs">{r.action}</code> },
          { key: "resource_type", header: "Resource", render: (r) => label(r.resource_type) },
        ]}
        actions={(r) => (r.before || r.after) ? <Button size="sm" variant="ghost" onClick={() => setView(r)}>Details</Button> : null} />
      <Dialog open={!!view} onClose={() => setView(null)} title={view?.action ?? ""} wide>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div><p className="mb-1 text-xs font-semibold text-muted">Before</p><pre className="max-h-96 overflow-auto rounded bg-canvas p-3 text-xs">{JSON.stringify(view?.before, null, 2) ?? "—"}</pre></div>
          <div><p className="mb-1 text-xs font-semibold text-muted">After</p><pre className="max-h-96 overflow-auto rounded bg-canvas p-3 text-xs">{JSON.stringify(view?.after, null, 2) ?? "—"}</pre></div>
        </div>
      </Dialog>
    </>
  );
}

