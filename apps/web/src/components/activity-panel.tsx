"use client";

import { CheckCircle2, Circle } from "lucide-react";
import { useState } from "react";
import { api, type Page } from "@/lib/api";
import { dateTime, label } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { FormDialog, type FieldDef } from "./form";
import { useToast } from "./toast";
import { Badge, Button, Card, CardHeader, Spinner, cn } from "./ui";

export type Activity = {
  id: string; type: string; subject: string; description: string | null; due_at: string | null; done_at: string | null;
  priority: string; assigned_to: string | null; related_type: string | null; related_id: string | null; created_at: string; version: number;
};

export const ACTIVITY_FIELDS: FieldDef[] = [
  { name: "type", label: "Type", type: "select", required: true, options: ["task", "call", "meeting", "note", "email"].map((v) => ({ value: v, label: label(v) })) },
  { name: "priority", label: "Priority", type: "select", required: true, options: ["low", "normal", "high"].map((v) => ({ value: v, label: label(v) })) },
  { name: "subject", label: "Subject", required: true, colSpan: 2 },
  { name: "due_at", label: "Due", type: "datetime", hidden: (v) => v.type === "note" },
  { name: "assigned_to", label: "Assign to", type: "member" },
  { name: "description", label: "Details", type: "textarea" },
];

export function ActivityPanel({ relatedType, relatedId }: { relatedType: string; relatedId: string }) {
  const { can } = useSession();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const { data, loading, reload } = useQuery<Page<Activity>>(`/crm/activities?related_type=${relatedType}&related_id=${relatedId}&limit=50`);
  if (!can("crm.activity.read_all", "crm.activity.read_own")) return null;
  return (
    <Card>
      <CardHeader title="Activity & tasks" action={can("crm.activity.create") && <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>Add</Button>} />
      {loading && !data ? <div className="p-5"><Spinner /></div> : (
        <ul className="divide-y divide-line">
          {!data?.data.length && <li className="px-5 py-6 text-center text-sm text-muted">No activity yet.</li>}
          {data?.data.map((a) => (
            <li key={a.id} className="flex gap-3 px-5 py-3">
              {a.type === "task" ? (
                <button aria-label={a.done_at ? "Mark open" : "Mark done"} disabled={!can("crm.activity.update")}
                  onClick={async () => { try { await api.patch(`/crm/activities/${a.id}`, { done: !a.done_at }); reload(); } catch (e) { toast.error(e); } }}>
                  {a.done_at ? <CheckCircle2 className="h-5 w-5 text-green-600" /> : <Circle className="h-5 w-5 text-muted" />}
                </button>
              ) : <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand" />}
              <div className="min-w-0 flex-1">
                <p className={cn("text-sm font-medium", a.done_at && a.type === "task" && "text-muted line-through")}>{a.subject}</p>
                {a.description && <p className="mt-0.5 whitespace-pre-line text-sm text-muted">{a.description}</p>}
                <p className="mt-1 flex flex-wrap gap-2 text-xs text-muted">
                  <Badge>{a.type}</Badge>
                  {a.due_at && <span>Due {dateTime(a.due_at)}</span>}
                  <span>Logged {dateTime(a.created_at)}</span>
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
      <FormDialog open={open} onClose={() => setOpen(false)} title="Log activity" fields={ACTIVITY_FIELDS}
        initial={{ type: "note", priority: "normal" }}
        submit={async (v) => { await api.post("/crm/activities", { ...v, related_type: relatedType, related_id: relatedId }); toast.success("Activity added"); reload(); }} />
    </Card>
  );
}
