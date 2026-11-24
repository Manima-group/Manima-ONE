"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, ErrorState, Field, Input, Loading } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { useSession, type Me } from "@/lib/session";

type Preview = { email: string; name: string | null; company: string; existing_user: boolean };

export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const { setMe } = useSession();
  const { data, error, loading } = useQuery<Preview>(`/invitations/${token}`);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorState error={error ?? { message: "Invitation not found" }} />;

  async function accept(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const me = await api.post<Me>("/invitations/accept", { token, name: name || data!.name, password });
      setMe(me);
      router.replace("/dashboard");
    } catch (e2) {
      setErr((e2 as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={accept} className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Join {data.company}</h1>
        <p className="mt-1 text-sm text-muted">Invitation for {data.email}</p>
      </div>
      {err && <Alert tone="red">{err}</Alert>}
      {!data.existing_user && <Field label="Your name" required><Input value={name || data.name || ""} onChange={(e) => setName(e.target.value)} required /></Field>}
      <Field label={data.existing_user ? "Your existing password" : "Choose a password"} required
        hint={data.existing_user ? "You already have a Manima One account." : "10+ characters with an uppercase letter and a digit."}>
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </Field>
      <Button type="submit" className="w-full" size="lg" loading={busy}>Accept invitation</Button>
    </form>
  );
}
