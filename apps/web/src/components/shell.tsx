"use client";

import {
  BarChart3, Bell, Boxes, Building2, ChevronDown, ClipboardList, CreditCard, FileText, Gauge, HeartPulse, Layers,
  LayoutDashboard, LogOut, Menu, Package, ReceiptText, ScrollText, Settings, ShieldCheck, ShoppingCart, Truck, User,
  Users, Wallet, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Page } from "@/lib/api";
import { ago } from "@/lib/format";
import { useSession } from "@/lib/session";
import { Button, Loading, cn } from "./ui";

type NavItem = { href: string; label: string; icon: React.ElementType; show?: boolean };
type NavGroup = { label: string; items: NavItem[] };

function useWorkspaceNav(): NavGroup[] {
  const { can, moduleOn } = useSession();
  const g: NavGroup[] = [
    { label: "Workspace", items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/workspace/tasks", label: "My tasks", icon: ClipboardList, show: moduleOn("crm") && can("crm.activity.read_all", "crm.activity.read_own") },
    ] },
    { label: "CRM", items: [
      { href: "/crm/leads", label: "Leads", icon: Users, show: moduleOn("crm") && can("crm.lead.read_all", "crm.lead.read_own") },
      { href: "/crm/accounts", label: "Customers", icon: Building2, show: moduleOn("crm") && can("crm.account.read") },
      { href: "/crm/contacts", label: "Contacts", icon: User, show: moduleOn("crm") && can("crm.account.read") },
      { href: "/crm/opportunities", label: "Pipeline", icon: Gauge, show: moduleOn("crm") && can("crm.opportunity.read_all", "crm.opportunity.read_own") },
      { href: "/crm/activities", label: "Activities", icon: ScrollText, show: moduleOn("crm") && can("crm.activity.read_all", "crm.activity.read_own") },
    ] },
    { label: "Sales", items: [
      { href: "/catalog/items", label: "Catalog", icon: Package, show: moduleOn("catalog") && can("catalog.item.read") },
      { href: "/sales/quotations", label: "Quotations", icon: FileText, show: moduleOn("sales") && can("sales.quotation.read_all", "sales.quotation.read_own") },
      { href: "/sales/orders", label: "Sales orders", icon: ShoppingCart, show: moduleOn("sales") && can("sales.order.read") },
    ] },
    { label: "Billing", items: [
      { href: "/billing/invoices", label: "Invoices", icon: ReceiptText, show: moduleOn("invoicing") && can("invoicing.invoice.read") },
      { href: "/billing/credit-notes", label: "Credit notes", icon: FileText, show: moduleOn("invoicing") && can("invoicing.note.read") },
      { href: "/billing/debit-notes", label: "Debit notes", icon: FileText, show: moduleOn("invoicing") && can("invoicing.note.read") },
      { href: "/billing/payments", label: "Payments", icon: Wallet, show: moduleOn("payments") && can("payments.payment.read") },
    ] },
    { label: "Operations", items: [
      { href: "/inventory/stock", label: "Inventory", icon: Boxes, show: moduleOn("inventory") && can("inventory.stock.read") },
      { href: "/procurement/purchase-orders", label: "Purchase orders", icon: Truck, show: moduleOn("procurement") && can("procurement.po.read") },
      { href: "/procurement/vendors", label: "Vendors", icon: Building2, show: moduleOn("procurement") && can("procurement.vendor.read") },
    ] },
    { label: "Insights", items: [
      { href: "/reports", label: "Reports", icon: BarChart3, show: can("reports.sales.read", "reports.receivables.read", "gst.report.read", "reports.inventory.read") },
    ] },
    { label: "Company", items: [
      { href: "/settings/company", label: "Settings", icon: Settings, show: can("core.settings.read", "core.settings.manage", "core.member.read", "core.member.manage", "core.role.manage", "core.module.manage", "core.audit.read", "core.billing.read") },
    ] },
  ];
  return g.map((x) => ({ ...x, items: x.items.filter((i) => i.show !== false) })).filter((x) => x.items.length);
}

const PLATFORM_NAV: NavGroup[] = [
  { label: "Platform", items: [
    { href: "/admin", label: "Dashboard", icon: LayoutDashboard },
    { href: "/admin/tenants", label: "Tenants", icon: Building2 },
    { href: "/admin/plans", label: "Subscription plans", icon: CreditCard },
    { href: "/admin/modules", label: "Modules & features", icon: Layers },
    { href: "/admin/users", label: "Users & access", icon: ShieldCheck },
    { href: "/admin/audit", label: "Audit log", icon: ScrollText },
    { href: "/admin/health", label: "System health", icon: HeartPulse },
  ] },
];

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<(Page<{ id: string; title: string; body: string | null; link: string | null; read_at: string | null; created_at: string }> & { unread: number }) | null>(null);
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const load = useCallback(
    () => api.get<typeof data>("/notifications?limit=8").then(setData).catch(() => undefined),
    [],
  );
  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  return (
    <div className="relative" ref={ref}>
      <Button variant="ghost" size="icon" aria-label="Notifications" onClick={() => { setOpen(!open); if (!open) load(); }}>
        <Bell className="h-5 w-5" />
        {!!data?.unread && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-semibold text-white">{data.unread}</span>}
      </Button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-80 rounded-lg border border-line bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <span className="text-sm font-semibold">Notifications</span>
            <button className="text-xs text-brand hover:underline" onClick={async () => { await api.post("/notifications:read-all"); load(); }}>Mark all read</button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {!data?.data.length && <p className="px-4 py-8 text-center text-sm text-muted">You&apos;re all caught up.</p>}
            {data?.data.map((n) => (
              <button key={n.id} className={cn("block w-full border-b border-line px-4 py-2.5 text-left last:border-0 hover:bg-canvas", !n.read_at && "bg-brand-soft/60")}
                onClick={async () => { await api.post(`/notifications/${n.id}:read`); setOpen(false); load(); if (n.link) router.push(n.link); }}>
                <p className="text-sm font-medium">{n.title}</p>
                {n.body && <p className="truncate text-xs text-muted">{n.body}</p>}
                <p className="mt-0.5 text-[11px] text-muted">{ago(n.created_at)}</p>
              </button>
            ))}
          </div>
          <Link href="/notifications" className="block border-t border-line px-4 py-2 text-center text-xs text-brand hover:bg-canvas" onClick={() => setOpen(false)}>View all</Link>
        </div>
      )}
    </div>
  );
}

function UserMenu({ platform }: { platform?: boolean }) {
  const { me, logout, switchTenant, canPlatform } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  if (!me) return null;
  return (
    <div className="relative" ref={ref}>
      <button className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-canvas" onClick={() => setOpen(!open)} aria-haspopup="menu">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand text-sm font-semibold text-white">{me.user.name.slice(0, 1).toUpperCase()}</span>
        <span className="hidden text-left sm:block">
          <span className="block text-sm font-medium leading-tight">{me.user.name}</span>
          <span className="block text-xs leading-tight text-muted">{platform ? "Manima platform" : me.active_tenant?.display_name}</span>
        </span>
        <ChevronDown className="h-4 w-4 text-muted" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-40 mt-2 w-64 rounded-lg border border-line bg-white py-1 shadow-lg">
          <p className="px-3 py-2 text-xs text-muted">{me.user.email}</p>
          {me.memberships.length > 0 && <p className="px-3 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Companies</p>}
          {me.memberships.map((m) => (
            <button key={m.tenant_id} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-canvas"
              onClick={() => switchTenant(m.tenant_id)}>
              <span className="truncate">{m.name}</span>
              {!platform && me.active_tenant?.id === m.tenant_id && <span className="text-xs text-brand">Active</span>}
            </button>
          ))}
          <div className="my-1 border-t border-line" />
          {platform ? null : <Link href="/profile" className="block px-3 py-2 text-sm hover:bg-canvas" onClick={() => setOpen(false)}>My profile</Link>}
          {!platform && canPlatform("platform.tenant.read") && <Link href="/admin" className="block px-3 py-2 text-sm hover:bg-canvas">Platform admin</Link>}
          {platform && me.memberships.length > 0 && <Link href="/dashboard" className="block px-3 py-2 text-sm hover:bg-canvas">Company workspace</Link>}
          <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-600 hover:bg-canvas" onClick={logout}>
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children, platform }: { children: React.ReactNode; platform?: boolean }) {
  const { me, loading } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  // The drawer is open only for the path it was opened on, so navigating closes it.
  const [mobileOpenPath, setMobileOpenPath] = useState<string | null>(null);
  const mobileOpen = mobileOpenPath === pathname;
  const setMobileOpen = (o: boolean) => setMobileOpenPath(o ? pathname : null);
  const wsNav = useWorkspaceNav();
  const nav = platform ? PLATFORM_NAV : wsNav;

  useEffect(() => {
    if (loading) return;
    if (!me) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (platform && !me.platform_permissions.length) router.replace("/dashboard");
    else if (!platform && !me.active_tenant) router.replace(me.platform_permissions.length ? "/admin" : "/no-company");
  }, [me, loading, platform, router, pathname]);

  if (loading || !me || (platform ? !me.platform_permissions.length : !me.active_tenant)) return <Loading />;
  const suspended = !platform && me.active_tenant?.status === "suspended";

  const sidebar = (
    <nav className="flex h-full flex-col">
      <div className="flex h-14 items-center gap-2 border-b border-line px-5">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">M</span>
        <span className="font-semibold">Manima One</span>
        {platform && <span className="rounded bg-ink px-1.5 py-0.5 text-[10px] font-semibold text-white">ADMIN</span>}
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {nav.map((g) => (
          <div key={g.label}>
            <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{g.label}</p>
            {g.items.map((i) => {
              const active = i.href === "/admin" || i.href === "/dashboard" ? pathname === i.href : pathname.startsWith(i.href.split("?")[0].replace(/\/company$/, ""));
              const Icon = i.icon;
              return (
                <Link key={i.href} href={i.href} className={cn("flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm",
                  active ? "bg-brand-soft font-medium text-brand" : "text-ink/80 hover:bg-canvas")}>
                  <Icon className="h-4 w-4" /> {i.label}
                </Link>
              );
            })}
          </div>
        ))}
      </div>
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="no-print fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-line bg-white lg:block">{sidebar}</aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-white shadow-xl">
            <button className="absolute right-3 top-4" onClick={() => setMobileOpen(false)} aria-label="Close menu"><X className="h-5 w-5" /></button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col lg:pl-60">
        <header className="no-print sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-white/95 px-4 backdrop-blur">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></Button>
          <div className="hidden text-sm text-muted lg:block">{platform ? "Platform Control Centre" : me.active_tenant?.display_name}</div>
          <div className="flex items-center gap-1">
            {!platform && <NotificationBell />}
            <UserMenu platform={platform} />
          </div>
        </header>
        {suspended && <div className="no-print bg-red-600 px-4 py-2 text-center text-sm text-white">This company account is suspended. Data is read-only — contact Manima support.</div>}
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
