"use client";

import { Copy, UserPlus } from "lucide-react";
import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Badge, Button, Card, CardHeader, Checkbox, Dialog, Field, Input, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { date, dateTime } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Role = { id: string; key: string; name: string };
type Member = { id: string; user_id: string; name: string; email: string; status: string; title: string | null; department: string | null;
  joined_at: string | null; last_login_at: string | null; roles: Role[] };
type Invite = { id: string; email: string; name: string | null; roles: string[]; expires_at: string; expired: boolean };

function RolePicker({ roles, value, onChange }: { roles: Role[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {roles.map((r) => (
        <Checkbox key={r.id} label={r.name} checked={value.includes(r.id)} onChange={(e) => onChange(e.target.checked ? [...value, r.id] : value.filter((x) => x !== r.id))} />
      ))}
    </div>
  );
}

export default function Employees() {
  const { can, me } = useSession();
  const toast = useToast();
  const manage = can("core.member.manage");
  const roles = useQuery<Role[]>("/tenant/roles");
  const invites = useQuery<Invite[]>(manage ? "/tenant/invitations" : null);
  const [key, setKey] = useState(0);
  const [inv, setInv] = useState<{ email: string; name: string; role_ids: string[] } | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [edit, setEdit] = useState<Member | null>(null);
  const [editRoles, setEditRoles] = useState<string[]>([]);
  const [editTitle, setEditTitle] = useState({ title: "", department: "" });
  const [err, setErr] = useState<string | null>(null);

  const sendInvite = async () => {
    try {
      setErr(null);
      const r = await api.post<{ accept_path: string }>("/tenant/invitations", inv);
      setLink(`${window.location.origin}${r.accept_path}`);
      setInv(null);
      invites.reload();
      toast.success("Invitation created");
    } catch (e) { setErr((e as ApiError).message); }
  };

  return (
    <>
      <PageHeader title="Employees" crumbs={[{ label: "Settings" }, { label: "Employees" }]}
        actions={manage && <Button onClick={() => { setErr(null); setInv({ email: "", name: "", role_ids: [] }); }}><UserPlus className="h-4 w-4" />Invite employee</Button>} />
      {link && <div className="mb-4"><Alert tone="green">
        Share this one-time invitation link (valid 7 days): <code className="break-all">{link}</code>
        <Button size="sm" variant="secondary" className="ml-2" onClick={() => { navigator.clipboard?.writeText(link); toast.success("Link copied"); }}><Copy className="h-3 w-3" />Copy</Button>
      </Alert></div>}
      <DataTable<Member> endpoint="/tenant/members" reloadKey={key} searchPlaceholder="Search name, email, title"
        filters={[{ key: "status", label: "Status", options: [{ value: "active", label: "Active" }, { value: "removed", label: "Removed" }] },
          { key: "role_id", label: "Role", options: (roles.data ?? []).map((r) => ({ value: r.id, label: r.name })) }]}
        columns={[
          { key: "name", header: "Name", render: (r) => <div><p className="font-medium">{r.name}{r.user_id === me?.user.id && <span className="text-xs text-muted"> (you)</span>}</p><p className="text-xs text-muted">{r.email}</p></div> },
          { key: "title", header: "Title", render: (r) => [r.title, r.department].filter(Boolean).join(" · ") || "—" },
          { key: "roles", header: "Roles", render: (r) => <div className="flex flex-wrap gap-1">{r.roles.map((x) => <Badge key={x.id} tone={x.key === "owner" ? "orange" : "gray"}>{x.name}</Badge>)}</div> },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "joined_at", header: "Joined", render: (r) => date(r.joined_at) },
          { key: "last_login_at", header: "Last sign-in", render: (r) => dateTime(r.last_login_at) },
        ]}
        actions={(r) => manage && (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="ghost" onClick={() => { setErr(null); setEdit(r); setEditRoles(r.roles.map((x) => x.id)); setEditTitle({ title: r.title ?? "", department: r.department ?? "" }); }}>Edit</Button>
            {r.user_id !== me?.user.id && (
              <Button size="sm" variant="ghost" onClick={async () => {
                try { await api.patch(`/tenant/members/${r.id}`, { status: r.status === "active" ? "removed" : "active" }); toast.success(r.status === "active" ? "Access removed" : "Access restored"); setKey((k) => k + 1); }
                catch (e) { toast.error(e); }
              }}>{r.status === "active" ? "Remove" : "Restore"}</Button>
            )}
          </div>
        )} />
      {manage && !!invites.data?.length && (
        <Card className="mt-6">
          <CardHeader title="Pending invitations" />
          <ul className="divide-y divide-line text-sm">
            {invites.data.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5">
                <span>{i.email} <span className="text-muted">· {i.roles.join(", ")}</span> {i.expired ? <Badge tone="red">expired</Badge> : <span className="text-xs text-muted">expires {date(i.expires_at)}</span>}</span>
                <Button size="sm" variant="ghost" onClick={async () => { await api.del(`/tenant/invitations/${i.id}`); toast.success("Invitation revoked"); invites.reload(); }}>Revoke</Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Dialog open={!!inv} onClose={() => setInv(null)} title="Invite employee"
        footer={<><Button variant="secondary" onClick={() => setInv(null)}>Cancel</Button><Button onClick={sendInvite} disabled={!inv?.email || !inv.role_ids.length}>Create invitation</Button></>}>
        {inv && <div className="space-y-4">
          {err && <Alert tone="red">{err}</Alert>}
          <Field label="Email" required><Input type="email" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} /></Field>
          <Field label="Name"><Input value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} /></Field>
          <Field label="Roles" required><RolePicker roles={roles.data ?? []} value={inv.role_ids} onChange={(role_ids) => setInv({ ...inv, role_ids })} /></Field>
        </div>}
      </Dialog>
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={`Edit ${edit?.name ?? ""}`}
        footer={<><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button onClick={async () => {
          try { setErr(null); await api.patch(`/tenant/members/${edit!.id}`, { role_ids: editRoles, ...editTitle }); toast.success("Employee updated", "Their open sessions were signed out so new access applies."); setEdit(null); setKey((k) => k + 1); }
          catch (e) { setErr((e as ApiError).message); }
        }}>Save</Button></>}>
        <div className="space-y-4">
          {err && <Alert tone="red">{err}</Alert>}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Title"><Input value={editTitle.title} onChange={(e) => setEditTitle({ ...editTitle, title: e.target.value })} /></Field>
            <Field label="Department"><Input value={editTitle.department} onChange={(e) => setEditTitle({ ...editTitle, department: e.target.value })} /></Field>
          </div>
          <Field label="Roles"><RolePicker roles={roles.data ?? []} value={editRoles} onChange={setEditRoles} /></Field>
        </div>
      </Dialog>
    </>
  );
}
