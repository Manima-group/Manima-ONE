"use client";

import { ACTIVITY_FIELDS, type Activity } from "@/components/activity-panel";
import { ResourcePage } from "@/components/page";
import { StatusBadge } from "@/components/ui";
import { dateTime, label } from "@/lib/format";

export default function ActivitiesPage() {
  return (
    <ResourcePage<Activity & Record<string, unknown>> title="Activities" nounSingular="activity" crumbs={[{ label: "CRM" }, { label: "Activities" }]}
      endpoint="/crm/activities" module="crm" fields={ACTIVITY_FIELDS} createPerm="crm.activity.create" updatePerm="crm.activity.update"
      deletePerm="crm.activity.delete" defaults={{ type: "task", priority: "normal" }}
      filters={[{ key: "type", label: "Type", options: ["task", "call", "meeting", "note", "email"].map((v) => ({ value: v, label: label(v) })) },
        { key: "status", label: "Status", options: [{ value: "open", label: "Open" }, { value: "done", label: "Done" }, { value: "overdue", label: "Overdue" }] }]}
      columns={[
        { key: "subject", header: "Subject", render: (r) => <span className="font-medium">{r.subject}</span> },
        { key: "type", header: "Type", render: (r) => label(r.type) },
        { key: "related_type", header: "Related to", render: (r) => r.related_type ? label(r.related_type) : "—" },
        { key: "priority", header: "Priority", render: (r) => <StatusBadge status={r.priority} /> },
        { key: "due_at", header: "Due", render: (r) => dateTime(r.due_at) },
        { key: "done_at", header: "Status", render: (r) => r.done_at ? <StatusBadge status="delivered" /> : <StatusBadge status="open" /> },
      ]} />
  );
}
