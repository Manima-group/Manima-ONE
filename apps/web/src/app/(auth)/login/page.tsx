"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Alert, Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useSession, type Me } from "@/lib/session";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { setMe } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api.post<Me>("/auth/login", { email, password });
      setMe(me);
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : me.active_tenant ? "/dashboard" : me.platform_permissions.length ? "/admin" : "/no-company");
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-muted">Welcome back to Manima One.</p>
      </div>
      {error && <Alert tone="red">{error}</Alert>}
      <Field label="Email" required>
        <Input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
      </Field>
      <Field label="Password" required>
        <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </Field>
      <Button type="submit" className="w-full" size="lg" loading={busy}>Sign in</Button>
      <p className="text-center text-sm text-muted">
        New to Manima One? <Link href="/signup" className="font-medium text-brand hover:underline">Create a company account</Link>
      </p>
    </form>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
