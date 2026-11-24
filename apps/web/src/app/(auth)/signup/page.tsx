"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useStates } from "@/components/form";
import { Alert, Button, Field, Input, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useSession, type Me } from "@/lib/session";

export default function SignupPage() {
  const router = useRouter();
  const { setMe } = useSession();
  const { data: states } = useStates();
  const [v, setV] = useState({ company_name: "", name: "", email: "", password: "", state_code: "" });
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const fe = err?.fieldErrors() ?? {};

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const me = await api.post<Me>("/signup", { ...v, state_code: v.state_code || null });
      setMe(me);
      router.replace("/dashboard?welcome=1");
    } catch (e2) {
      setErr(e2 as ApiError);
    } finally {
      setBusy(false);
    }
  }
  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV({ ...v, [k]: e.target.value });

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Create your company</h1>
        <p className="mt-1 text-sm text-muted">14-day trial of the Growth plan. No card required.</p>
      </div>
      {err && <Alert tone="red">{err.message}</Alert>}
      <Field label="Company name" required error={fe.company_name}><Input value={v.company_name} onChange={set("company_name")} required /></Field>
      <Field label="State (for GST place of supply)" error={fe.state_code}>
        <Select value={v.state_code} onChange={set("state_code")}>
          <option value="">Select state…</option>
          {(states ?? []).map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </Select>
      </Field>
      <Field label="Your name" required error={fe.name}><Input value={v.name} onChange={set("name")} required /></Field>
      <Field label="Work email" required error={fe.email}><Input type="email" value={v.email} onChange={set("email")} required /></Field>
      <Field label="Password" required error={fe.password} hint="10+ characters with an uppercase letter and a digit.">
        <Input type="password" autoComplete="new-password" value={v.password} onChange={set("password")} required />
      </Field>
      <Button type="submit" className="w-full" size="lg" loading={busy}>Create account</Button>
      <p className="text-center text-sm text-muted">Already have an account? <Link href="/login" className="font-medium text-brand hover:underline">Sign in</Link></p>
    </form>
  );
}
