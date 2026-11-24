"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { FormDialog } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Badge, Button, Checkbox, Dialog, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useSession } from "@/lib/session";

type U = { id: string; email: string; name: string; status: string; platform_roles: string[]; tenants: number; last_login_at: string | null };
const ROLES = [["super_admin", "Super Admin"], ["ops", "Operations"], ["support", "Support"]];

export default function UsersAdmin() {
  const { canPlatform, me } = useSession();
  const toast = useToast();
  const [key, setKey] = useState(0);
  const [open, setOpen] = useState(false);
  const [roles, setRoles] = useState<U | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const manage = canPlatform("platform.user.manage");
  return (
    <>
      <PageHeader title="Users & access" crumbs={[{ label: "Platform" }, { label: "Users" }]}
        actions={manage && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" />Add staff user</Button>} />
      <DataTable<U> endpoint="/platform/users" reloadKey={key} searchPlaceholder="Search name or email"
        filters={[{ key: "staff_only", label: "Users", options: [{ value: "true", label: "Manima staff only" }] }]}
        columns={[
          { key: "name", header: "User", render: (r) => <div><p className="font-medium">{r.name}</p><p className="text-xs text-muted">{r.email}</p></div> },
          { key: "platform_roles", header: "Platform roles", render: (r) => <div className="flex gap-1">{r.platform_roles.length ? r.platform_roles.map((x) => <Badge key={x} tone="orange">{x}</Badge>) : <span className="text-muted">—</span>}</div> },
          { key: "tenants", header: "Companies", render: (r) => r.tenants },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
          { key: "last_login_at", header: "Last sign-in", render: (r) => dateTime(r.last_login_at) },
        ]}
        actions={(r) => manage && r.id !== me?.user.id && (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="ghost" onClick={() => { setRoles(r); setSel(r.platform_roles); }}>Roles</Button>
            <Button size="sm" variant="ghost" onClick={async () => { try { await api.patch(`/platform/users/${r.id}`, { status: r.status === "active" ? "disabled" : "active" }); toast.success("User updated"); setKey((k) => k + 1); } catch (e) { toast.error(e); } }}>
              {r.status === "active" ? "Disable" : "Enable"}
            </Button>
          </div>
        )} />
      <FormDialog open={open} onClose={() => setOpen(false)} title="Add Manima staff user" submitLabel="Create user"
        fields={[{ name: "name", label: "Name", required: true }, { name: "email", label: "Email", type: "email", required: true },
          { name: "password", label: "Initial password", required: true, hint: "10+ chars, uppercase and digit" },
          { name: "role", label: "Platform role", type: "select", required: true, options: ROLES.map(([value, label]) => ({ value, label })) }]}
        initial={{ role: "support" }}
        submit={async (v) => { await api.post("/platform/users", { name: v.name, email: v.email, password: v.password, platform_roles: [v.role] }); toast.success("Staff user created"); setKey((k) => k + 1); }} />
      <Dialog open={!!roles} onClose={() => setRoles(null)} title={`Platform roles: ${roles?.name ?? ""}`}
        footer={<><Button variant="secondary" onClick={() => setRoles(null)}>Cancel</Button><Button onClick={async () => {
          try { await api.patch(`/platform/users/${roles!.id}`, { platform_roles: sel }); toast.success("Roles updated"); setRoles(null); setKey((k) => k + 1); } catch (e) { toast.error(e); }
        }}>Save</Button></>}>
        <div className="space-y-2">{ROLES.map(([k, l]) => <div key={k}><Checkbox label={l} checked={sel.includes(k)} onChange={(e) => setSel(e.target.checked ? [...sel, k] : sel.filter((x) => x !== k))} /></div>)}</div>
      </Dialog>
    </>
  );
}
