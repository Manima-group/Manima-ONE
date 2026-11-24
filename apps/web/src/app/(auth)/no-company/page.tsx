"use client";

import Link from "next/link";
import { Button } from "@/components/ui";
import { useSession } from "@/lib/session";

export default function NoCompany() {
  const { me, logout } = useSession();
  return (
    <div className="space-y-4 text-center">
      <h1 className="text-xl font-semibold">No active company</h1>
      <p className="text-sm text-muted">{me?.user.email} is not an active member of any company. Ask your administrator for a new invitation, or create a company.</p>
      <div className="flex justify-center gap-2">
        <Link href="/signup"><Button>Create a company</Button></Link>
        <Button variant="secondary" onClick={logout}>Sign out</Button>
      </div>
    </div>
  );
}
