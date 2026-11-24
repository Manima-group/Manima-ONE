"use client";

import { useRouter } from "next/navigation";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page";
import { Badge, Button } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useState } from "react";

type N = { id: string; kind: string; title: string; body: string | null; link: string | null; read_at: string | null; created_at: string };

export default function Notifications() {
  const router = useRouter();
  const [key, setKey] = useState(0);
  return (
    <>
      <PageHeader title="Notifications" crumbs={[{ label: "Workspace" }, { label: "Notifications" }]}
        actions={<Button variant="secondary" onClick={async () => { await api.post("/notifications:read-all"); setKey((k) => k + 1); }}>Mark all read</Button>} />
      <DataTable<N> endpoint="/notifications" reloadKey={key} filters={[{ key: "unread", label: "Show", options: [{ value: "true", label: "Unread only" }] }]}
        columns={[
          { key: "title", header: "Notification", render: (r) => <div><p className={r.read_at ? "" : "font-semibold"}>{r.title}</p>{r.body && <p className="text-xs text-muted">{r.body}</p>}</div> },
          { key: "kind", header: "Type", render: (r) => <Badge>{r.kind}</Badge> },
          { key: "created_at", header: "When", render: (r) => dateTime(r.created_at) },
        ]}
        actions={(r, reload) => (
          <div className="flex justify-end gap-1">
            {r.link && <Button size="sm" variant="ghost" onClick={async () => { await api.post(`/notifications/${r.id}:read`); router.push(r.link!); }}>Open</Button>}
            {!r.read_at && <Button size="sm" variant="ghost" onClick={async () => { await api.post(`/notifications/${r.id}:read`); reload(); }}>Mark read</Button>}
          </div>
        )} />
    </>
  );
}
