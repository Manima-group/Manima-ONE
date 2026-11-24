"use client";

// Owned UI primitives in the shadcn/ui style (Tailwind + variants), themed white/orange/grey.
import { clsx, type ClassValue } from "clsx";
import { Loader2, X } from "lucide-react";
import { forwardRef, useEffect } from "react";
import { twMerge } from "tailwind-merge";

export const cn = (...c: ClassValue[]) => twMerge(clsx(c));

type BtnVariant = "primary" | "secondary" | "ghost" | "danger" | "outline";
const btnBase =
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap";
const btnVariants: Record<BtnVariant, string> = {
  primary: "bg-brand text-white hover:bg-brand-hover shadow-sm",
  secondary: "bg-white text-ink border border-line hover:bg-canvas shadow-sm",
  outline: "border border-brand text-brand hover:bg-brand-soft",
  ghost: "text-muted hover:bg-canvas hover:text-ink",
  danger: "bg-red-600 text-white hover:bg-red-700 shadow-sm",
};
const btnSizes = { sm: "h-8 px-3", md: "h-9 px-4", lg: "h-11 px-6", icon: "h-9 w-9" };

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: keyof typeof btnSizes; loading?: boolean }
>(function Button({ className, variant = "primary", size = "md", loading, children, disabled, type = "button", ...p }, ref) {
  return (
    <button ref={ref} type={type} className={cn(btnBase, btnVariants[variant], btnSizes[size], className)} disabled={disabled || loading} {...p}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
});

const field =
  "w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink placeholder:text-muted/70 focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none disabled:bg-canvas disabled:text-muted";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ className, invalid, ...p }, ref) {
    return <input ref={ref} className={cn(field, "h-9", invalid && "border-red-500", className)} {...p} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function Textarea({ className, invalid, ...p }, ref) {
    return <textarea ref={ref} className={cn(field, "min-h-20", invalid && "border-red-500", className)} {...p} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }>(
  function Select({ className, invalid, children, ...p }, ref) {
    return (
      <select ref={ref} className={cn(field, "h-9 pr-8", invalid && "border-red-500", className)} {...p}>
        {children}
      </select>
    );
  },
);

export function Field({ label, error, hint, required, children, className }: {
  label: string; error?: string; hint?: string; required?: boolean; children: React.ReactNode; className?: string;
}) {
  return (
    <label className={cn("block space-y-1", className)}>
      <span className="text-sm font-medium text-ink">
        {label}
        {required && <span className="text-brand" aria-hidden="true"> *</span>}
      </span>
      {children}
      {error ? <span className="block text-xs text-red-600">{error}</span> : hint ? <span className="block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function Card({ className, children, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-lg border border-line bg-white shadow-sm", className)} {...p}>
      {children}
    </div>
  );
}

export function CardHeader({ title, action, subtitle }: { title: React.ReactNode; subtitle?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
      <div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

const tones: Record<string, string> = {
  gray: "bg-gray-100 text-gray-700",
  orange: "bg-orange-100 text-orange-800",
  green: "bg-green-100 text-green-800",
  red: "bg-red-100 text-red-700",
  blue: "bg-blue-100 text-blue-800",
  yellow: "bg-yellow-100 text-yellow-800",
  purple: "bg-purple-100 text-purple-800",
};

const STATUS_TONE: Record<string, string> = {
  draft: "gray", new: "blue", contacted: "yellow", qualified: "purple", converted: "green", lost: "red",
  sent: "blue", accepted: "green", rejected: "red", expired: "gray", superseded: "gray",
  confirmed: "blue", delivered: "green", cancelled: "red", issued: "green", unpaid: "orange",
  partially_paid: "yellow", paid: "green", overpaid: "purple", succeeded: "green", refunded: "red",
  active: "green", suspended: "red", trialing: "blue", enabled: "green", disabled: "gray", read_only: "yellow",
  draining: "yellow", open: "blue", won: "green", pending: "orange", pending_approval: "orange", approved: "green",
  not_required: "gray", in_transit: "blue", received: "green", partially_received: "yellow", invited: "blue",
  removed: "gray", requested: "orange", available: "green", registered: "gray", deprecated: "yellow", retired: "gray",
  ok: "green", degraded: "orange", down: "red", high: "red", normal: "gray", low: "gray",
};

export function Badge({ children, tone, className }: { children: React.ReactNode; tone?: string; className?: string }) {
  return <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone ?? "gray"], className)}>{children}</span>;
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return <Badge tone={STATUS_TONE[status] ?? "gray"}>{status.replace(/_/g, " ")}</Badge>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-5 w-5 animate-spin text-brand", className)} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: { message: string; code?: string } | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <p className="font-medium">{error.message}</p>
      {error.code && <p className="mt-1 text-xs text-red-600">Code: {error.code}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Alert({ tone = "orange", children }: { tone?: "orange" | "red" | "green" | "blue"; children: React.ReactNode }) {
  const t = { orange: "border-orange-200 bg-brand-soft text-orange-900", red: "border-red-200 bg-red-50 text-red-800",
    green: "border-green-200 bg-green-50 text-green-800", blue: "border-blue-200 bg-blue-50 text-blue-800" }[tone];
  return <div className={cn("rounded-md border px-4 py-3 text-sm", t)}>{children}</div>;
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 h-10 w-10 rounded-full bg-brand-soft ring-8 ring-brand-soft/50" />
      <p className="font-medium text-ink">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Dialog({ open, onClose, title, children, footer, wide }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh]" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className={cn("w-full rounded-lg bg-white shadow-xl", wide ? "max-w-3xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { key: string; label: string }[]; value: string; onChange: (k: string) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <button key={t.key} type="button" onClick={() => onChange(t.key)}
          className={cn("whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
            value === t.key ? "border-brand text-brand" : "border-transparent text-muted hover:text-ink")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: "brand" | "red" }) {
  return (
    <Card className="min-w-0 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={cn("mt-1 whitespace-nowrap text-2xl font-semibold tabular-nums", tone === "brand" && "text-brand", tone === "red" && "text-red-600")}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </Card>
  );
}

export function Checkbox({ label, ...p }: React.InputHTMLAttributes<HTMLInputElement> & { label: React.ReactNode }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" className="h-4 w-4 rounded border-line accent-[#F97316]" {...p} />
      {label}
    </label>
  );
}
