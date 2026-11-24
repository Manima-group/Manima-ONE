"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Loading } from "@/components/ui";
import { useSession } from "@/lib/session";

export default function Home() {
  const { me, loading } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else if (me.active_tenant) router.replace("/dashboard");
    else if (me.platform_permissions.length) router.replace("/admin");
    else router.replace("/no-company");
  }, [me, loading, router]);
  return <Loading />;
}
