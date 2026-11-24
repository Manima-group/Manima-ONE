"use client";

import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { qs, type Page } from "@/lib/api";
import { useDebounced, useQuery } from "@/lib/hooks";
import { Button, Card, EmptyState, ErrorState, Input, Select, Spinner, cn } from "./ui";

export type Column<T> = {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
  className?: string;
  align?: "right";
};

export type Filter = { key: string; label: string; options: { value: string; label: string }[] };

/** Server-paginated, searchable, filterable table bound to a list endpoint returning {data,total}. */
export function DataTable<T extends Record<string, unknown>>({
  endpoint, columns, filters = [], rowHref, actions, searchPlaceholder = "Search…", empty, reloadKey, extraParams, toolbar,
}: {
  endpoint: string;
  columns: Column<T>[];
  filters?: Filter[];
  rowHref?: (row: T) => string;
  actions?: (row: T, reload: () => void) => React.ReactNode;
  searchPlaceholder?: string;
  empty?: React.ReactNode;
  reloadKey?: unknown;
  extraParams?: Record<string, string | undefined>;
  toolbar?: React.ReactNode;
}) {
  const [q, setQ] = useState("");
  const router = useRouter();
  const [offset, setOffset] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const limit = 20;
  const dq = useDebounced(q);
  const url = useMemo(() => {
    const sep = endpoint.includes("?") ? "&" : "";
    const query = qs({ q: dq, limit, offset, ...values, ...extraParams });
    return endpoint + (sep && query ? sep + query.slice(1) : query);
  }, [endpoint, dq, offset, values, extraParams]);
  const { data, error, loading, reload } = useQuery<Page<T>>(url, [reloadKey]);
  const total = data?.total ?? 0;

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <div className="relative min-w-48 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted" />
          <Input className="pl-8" placeholder={searchPlaceholder} value={q} aria-label="Search"
            onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        </div>
        {filters.map((f) => (
          <Select key={f.key} className="w-auto min-w-36" aria-label={f.label} value={values[f.key] ?? ""}
            onChange={(e) => { setValues((v) => ({ ...v, [f.key]: e.target.value })); setOffset(0); }}>
            <option value="">{f.label}: All</option>
            {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
        ))}
        {toolbar}
        {loading && data && <Spinner className="h-4 w-4" />}
      </div>
      {error ? (
        <div className="p-4"><ErrorState error={error} onRetry={reload} /></div>
      ) : !data ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted"><Spinner /> Loading…</div>
      ) : data.data.length === 0 ? (
        empty ?? <EmptyState title={q || Object.values(values).some(Boolean) ? "No matches" : "Nothing here yet"}
          description={q ? "Try a different search or filter." : undefined} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                {columns.map((c) => <th key={c.key} className={cn("px-4 py-2.5 font-medium", c.align === "right" && "text-right", c.className)}>{c.header}</th>)}
                {actions && <th className="px-4 py-2.5" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.data.map((row, i) => (
                <tr key={(row.id as string) ?? (row.item_id as string) ?? i}
                  className={cn("hover:bg-canvas/70", rowHref && "cursor-pointer")}
                  onClick={rowHref ? (e) => {
                    // Whole row opens the record; clicks on links, buttons and inputs keep their own behaviour.
                    if ((e.target as HTMLElement).closest("a,button,input,select,textarea,label")) return;
                    if (window.getSelection()?.toString()) return;
                    router.push(rowHref(row));
                  } : undefined}>
                  {columns.map((c, ci) => {
                    const content = c.render ? c.render(row) : String(row[c.key] ?? "—");
                    return (
                      <td key={c.key} className={cn("px-4 py-2.5 align-middle", c.align === "right" && "text-right tabular-nums", c.className)}>
                        {rowHref && ci === 0 ? <Link href={rowHref(row)} className="font-medium text-ink hover:text-brand">{content}</Link> : content}
                      </td>
                    );
                  })}
                  {actions && <td className="px-4 py-2 text-right">{actions(row, reload)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && total > 0 && (
        <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-xs text-muted">
          <span>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
          <div className="flex gap-1">
            <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} aria-label="Previous page">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="secondary" size="sm" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)} aria-label="Next page">
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
