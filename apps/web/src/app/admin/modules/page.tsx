"use client";

import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Badge, Card, Checkbox, ErrorState, Loading, Select, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type M = { key: string; name: string; description: string; version: string; kind: string; depends_on: string[]; platform_state: string; tenants_enabled: number;
  feature: { enabled: boolean; kill_switch: boolean } | null };

export default function ModulesAdmin() {
  const { canPlatform } = useSession();
  const toast = useToast();
  const { data, error, loading, reload } = useQuery<M[]>("/platform/modules");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const run = async (p: Promise<unknown>, msg: string) => { try { await p; toast.success(msg); reload(); } catch (e) { toast.error(e); } };
  return (
    <>
      <PageHeader title="Modules & feature flags" crumbs={[{ label: "Platform" }, { label: "Modules" }]}
        subtitle="Publish/withdraw module versions and use the kill switch to stop writes for every tenant during an incident." />
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-canvas text-left text-xs uppercase text-muted"><tr><th className="px-4 py-2">Module</th><th className="px-4 py-2">Version</th><th className="px-4 py-2">Depends on</th>
              <th className="px-4 py-2">Tenants</th><th className="px-4 py-2">Platform state</th><th className="px-4 py-2">Feature flag</th><th className="px-4 py-2">Kill switch</th></tr></thead>
            <tbody className="divide-y divide-line">
              {data!.map((m) => (
                <tr key={m.key}>
                  <td className="px-4 py-2"><p className="font-medium">{m.name}</p><p className="text-xs text-muted">{m.description}</p></td>
                  <td className="px-4 py-2 font-mono text-xs">{m.version}</td>
                  <td className="px-4 py-2 text-xs">{m.depends_on.join(", ") || "—"}</td>
                  <td className="px-4 py-2">{m.tenants_enabled}</td>
                  <td className="px-4 py-2">{m.kind === "core" ? <Badge>core</Badge> : canPlatform("platform.module.publish") ? (
                    <Select className="h-8 w-36" value={m.platform_state} aria-label={`${m.name} platform state`}
                      onChange={(e) => run(api.patch(`/platform/modules/${m.key}`, { platform_state: e.target.value }), "Module state updated")}>
                      {["registered", "available", "deprecated", "retired"].map((s) => <option key={s} value={s}>{s}</option>)}
                    </Select>) : <StatusBadge status={m.platform_state} />}</td>
                  <td className="px-4 py-2">{m.feature && <Checkbox label={m.feature.enabled ? "Enabled" : "Off"} checked={m.feature.enabled} disabled={!canPlatform("platform.feature_flag.manage")}
                    onChange={(e) => run(api.patch(`/platform/features/${m.key}`, { enabled: e.target.checked }), "Flag updated")} />}</td>
                  <td className="px-4 py-2">{m.feature && <Checkbox label={m.feature.kill_switch ? <span className="font-medium text-red-600">ACTIVE</span> : "Off"} checked={m.feature.kill_switch}
                    disabled={!canPlatform("platform.feature_flag.manage")} onChange={(e) => run(api.patch(`/platform/features/${m.key}`, { kill_switch: e.target.checked }), e.target.checked ? "Kill switch activated" : "Kill switch released")} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
