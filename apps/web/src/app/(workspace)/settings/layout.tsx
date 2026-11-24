"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/components/ui";
import { useSession } from "@/lib/session";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { can } = useSession();
  const path = usePathname();
  const items = [
    { href: "/settings/company", label: "Company profile", show: can("core.settings.read", "core.settings.manage") },
    { href: "/settings/gst", label: "GST & numbering", show: can("core.settings.read", "core.gst.manage") },
    { href: "/settings/employees", label: "Employees", show: can("core.member.read", "core.member.manage") },
    { href: "/settings/roles", label: "Roles & permissions", show: can("core.role.manage") },
    { href: "/settings/modules", label: "Modules", show: can("core.module.manage") },
    { href: "/settings/subscription", label: "Subscription", show: can("core.billing.read", "core.settings.manage") },
    { href: "/settings/audit", label: "Audit log", show: can("core.audit.read") },
  ].filter((i) => i.show);
  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <nav className="no-print flex shrink-0 gap-1 overflow-x-auto lg:w-52 lg:flex-col" aria-label="Settings">
        {items.map((i) => (
          <Link key={i.href} href={i.href} className={cn("whitespace-nowrap rounded-md px-3 py-2 text-sm",
            path.startsWith(i.href) ? "bg-brand-soft font-medium text-brand" : "text-ink/80 hover:bg-white")}>{i.label}</Link>
        ))}
      </nav>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
