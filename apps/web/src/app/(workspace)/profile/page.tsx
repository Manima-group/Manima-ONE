"use client";

import { useState } from "react";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Badge, Button, Card, CardHeader, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useSession, type Me } from "@/lib/session";

export default function Profile() {
  const { me, setMe } = useSession();
  const toast = useToast();
  const [p, setP] = useState({ name: me?.user.name ?? "", phone: me?.user.phone ?? "" });
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [err, setErr] = useState<string | null>(null);
  if (!me) return null;
  const membership = me.memberships.find((m) => m.tenant_id === me.active_tenant?.id);
  return (
    <>
      <PageHeader title="My profile" crumbs={[{ label: "Workspace" }, { label: "Profile" }]} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Personal details" />
          <div className="space-y-4 p-5">
            <Field label="Email"><Input value={me.user.email} disabled /></Field>
            <Field label="Name"><Input value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} /></Field>
            <Field label="Phone"><Input value={p.phone} onChange={(e) => setP({ ...p, phone: e.target.value })} /></Field>
            <div><p className="mb-1 text-sm font-medium">Roles in {me.active_tenant?.display_name}</p><div className="flex flex-wrap gap-1">{membership?.roles.map((r) => <Badge key={r} tone="orange">{r}</Badge>)}</div></div>
            <Button onClick={async () => { try { setMe(await api.patch<Me>("/me/profile", p)); toast.success("Profile saved"); } catch (e) { toast.error(e); } }}>Save profile</Button>
          </div>
        </Card>
        <Card>
          <CardHeader title="Change password" />
          <div className="space-y-4 p-5">
            {err && <Alert tone="red">{err}</Alert>}
            <Field label="Current password"><Input type="password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
            <Field label="New password" hint="10+ characters with an uppercase letter and a digit."><Input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
            <Button onClick={async () => { try { setErr(null); await api.post("/me/password", pw); setPw({ current_password: "", new_password: "" }); toast.success("Password changed"); } catch (e) { setErr((e as ApiError).message); } }}>Update password</Button>
          </div>
        </Card>
      </div>
    </>
  );
}
