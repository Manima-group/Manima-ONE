"use client";

import { CheckCircle2, Circle, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ACTIVITY_FIELDS, type Activity } from "@/components/activity-panel";
import { FormDialog } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, StatusBadge, Tabs, cn } from "@/components/ui";
import { api, type Page } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

const LINKS: Record<string, string> = { lead: "/crm/leads/", account: "/crm/accounts/", opportunity: "/crm/opportunities" };

export default function MyTasks() {
  const { can, writable } = useSession();
  const toast = useToast();
  const [tab, setTab] = useState("open");
  const [open, setOpen] = useState(false);
  const { data, error, loading, reload } = useQuery<Page<Activity>>(`/crm/activities?assigned=me&type=task&status=${tab}&limit=100&sort=due_at`);
  return (
    <>
      <PageHeader title="My tasks" crumbs={[{ label: "Workspace" }, { label: "My tasks" }]}
        actions={can("crm.activity.create") && writable("crm") && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />New task</Button>} />
      <div className="mb-4"><Tabs tabs={[{ key: "open", label: "Open" }, { key: "overdue", label: "Overdue" }, { key: "done", label: "Completed" }]} value={tab} onChange={setTab} /></div>
      {error ? <ErrorState error={error} onRetry={reload} /> : loading && !data ? <Loading /> : (
        <Card>
          {!data?.data.length ? <EmptyState title={tab === "done" ? "No completed tasks" : "No tasks — nice work!"} /> : (
            <ul className="divide-y divide-line">
              {data.data.map((t) => {
                const overdue = !t.done_at && t.due_at && new Date(t.due_at) < new Date();
                return (
                  <li key={t.id} className="flex items-start gap-3 px-5 py-3">
                    <button aria-label={t.done_at ? "Reopen task" : "Complete task"} className="mt-0.5"
                      onClick={async () => { try { await api.patch(`/crm/activities/${t.id}`, { done: !t.done_at }); toast.success(t.done_at ? "Task reopened" : "Task completed"); reload(); } catch (e) { toast.error(e); } }}>
                      {t.done_at ? <CheckCircle2 className="h-5 w-5 text-green-600" /> : <Circle className="h-5 w-5 text-muted hover:text-brand" />}
                    </button>
                    <div className="min-w-0 flex-1">
                      <p className={cn("text-sm font-medium", t.done_at && "text-muted line-through")}>{t.subject}</p>
                      {t.description && <p className="text-sm text-muted">{t.description}</p>}
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                        <StatusBadge status={t.priority} />
                        {t.due_at && <span className={cn(overdue && "font-medium text-red-600")}>Due {dateTime(t.due_at)}</span>}
                        {t.related_type && t.related_id && LINKS[t.related_type] && (
                          <Link className="text-brand hover:underline" href={LINKS[t.related_type] + (t.related_type === "opportunity" ? "" : t.related_id)}>
                            <Badge tone="orange">{t.related_type}</Badge>
                          </Link>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      )}
      <FormDialog open={open} onClose={() => setOpen(false)} title="New task" fields={ACTIVITY_FIELDS.filter((f) => f.name !== "type")}
        initial={{ priority: "normal" }} submit={async (v) => { await api.post("/crm/activities", { ...v, type: "task" }); toast.success("Task created"); reload(); }} />
    </>
  );
}
