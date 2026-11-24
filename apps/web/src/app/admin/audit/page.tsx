"use client";

import { AuditTable } from "@/components/audit-table";
import { PageHeader } from "@/components/page";

export default function PlatformAudit() {
  return (
    <>
      <PageHeader title="Platform audit log" crumbs={[{ label: "Platform" }, { label: "Audit" }]} subtitle="Tenant lifecycle, plans, flags, overrides and staff access changes." />
      <AuditTable endpoint="/platform/audit" />
    </>
  );
}
