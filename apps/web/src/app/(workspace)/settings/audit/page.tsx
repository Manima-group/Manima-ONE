"use client";

import { AuditTable } from "@/components/audit-table";
import { PageHeader } from "@/components/page";

export default function Audit() {
  return (
    <>
      <PageHeader title="Audit log" crumbs={[{ label: "Settings" }, { label: "Audit log" }]} subtitle="Append-only record of every change in your company." />
      <AuditTable endpoint="/tenant/audit" />
    </>
  );
}
