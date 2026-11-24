"""Module manifests, permission catalogue and default role bundles.

Source of truth for registry sync (``manima.core.registry.sync``). Mirrors
MODULE_ARCHITECTURE.md / RBAC_PERMISSION_MATRIX.md (Distribution pack defaults).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleManifest:
    key: str
    name: str
    description: str
    kind: str  # core | business | pack
    version: str = "1.0.0"
    depends_on: tuple[str, ...] = ()
    permissions: dict[str, str] = field(default_factory=dict)
    sensitive: tuple[str, ...] = ()


MODULES: list[ModuleManifest] = [
    ModuleManifest(
        "core",
        "Platform core",
        "Company settings, users, roles, modules, audit",
        "core",
        permissions={
            "core.settings.read": "View company settings",
            "core.settings.manage": "Edit company profile and preferences",
            "core.gst.manage": "Manage GST registrations and number series",
            "core.member.read": "View employees",
            "core.member.manage": "Invite, update and remove employees",
            "core.role.manage": "Create and edit custom roles",
            "core.module.manage": "Enable or disable modules",
            "core.billing.read": "View subscription and usage",
            "core.audit.read": "View audit log",
        },
    ),
    ModuleManifest(
        "crm",
        "CRM",
        "Leads, accounts, contacts, pipeline, activities and tasks",
        "business",
        permissions={
            "crm.lead.read_all": "View all leads",
            "crm.lead.read_own": "View own leads",
            "crm.lead.create": "Create leads",
            "crm.lead.update": "Edit leads",
            "crm.lead.delete": "Delete leads",
            "crm.lead.convert": "Convert leads",
            "crm.account.read": "View accounts and contacts",
            "crm.account.create": "Create accounts and contacts",
            "crm.account.update": "Edit accounts and contacts",
            "crm.account.delete": "Delete accounts and contacts",
            "crm.opportunity.read_all": "View all opportunities",
            "crm.opportunity.read_own": "View own opportunities",
            "crm.opportunity.create": "Create opportunities",
            "crm.opportunity.update": "Edit opportunities",
            "crm.opportunity.delete": "Delete opportunities",
            "crm.activity.read_all": "View all activities and tasks",
            "crm.activity.read_own": "View own activities and tasks",
            "crm.activity.create": "Create activities and tasks",
            "crm.activity.update": "Edit activities and tasks",
            "crm.activity.delete": "Delete activities and tasks",
        },
    ),
    ModuleManifest(
        "catalog",
        "Product & service catalog",
        "Items, HSN/SAC, pricing",
        "business",
        permissions={
            "catalog.item.read": "View items",
            "catalog.item.create": "Create items",
            "catalog.item.update": "Edit items",
            "catalog.item.delete": "Delete items",
        },
    ),
    ModuleManifest(
        "compliance_gst",
        "GST compliance",
        "GST registrations, tax computation, GST reports",
        "business",
        permissions={"gst.report.read": "View GST reports"},
    ),
    ModuleManifest(
        "sales",
        "Sales",
        "Quotations and sales orders",
        "business",
        depends_on=("crm", "catalog", "compliance_gst"),
        permissions={
            "sales.quotation.read_all": "View all quotations",
            "sales.quotation.read_own": "View own quotations",
            "sales.quotation.create": "Create quotations",
            "sales.quotation.update": "Edit quotations",
            "sales.quotation.send": "Send quotations",
            "sales.quotation.approve": "Approve discounts / accept",
            "sales.quotation.delete": "Delete draft quotations",
            "sales.order.read": "View sales orders",
            "sales.order.create": "Create sales orders",
            "sales.order.update": "Confirm / deliver sales orders",
            "sales.order.cancel": "Cancel sales orders",
        },
    ),
    ModuleManifest(
        "invoicing",
        "Invoicing",
        "GST tax invoices, credit notes and debit notes",
        "business",
        depends_on=("crm", "catalog", "compliance_gst"),
        permissions={
            "invoicing.invoice.read": "View invoices",
            "invoicing.invoice.create": "Create draft invoices",
            "invoicing.invoice.issue": "Issue invoices",
            "invoicing.invoice.cancel": "Cancel invoices",
            "invoicing.note.read": "View credit/debit notes",
            "invoicing.note.create": "Create credit/debit notes",
            "invoicing.note.issue": "Issue credit/debit notes",
        },
        sensitive=("invoicing.invoice.cancel",),
    ),
    ModuleManifest(
        "payments",
        "Payments",
        "Payments received and allocations",
        "business",
        depends_on=("invoicing",),
        permissions={
            "payments.payment.read": "View payments",
            "payments.payment.create": "Record payments",
            "payments.payment.refund": "Refund / void payments",
        },
        sensitive=("payments.payment.refund",),
    ),
    ModuleManifest(
        "inventory",
        "Inventory",
        "Warehouses, stock ledger, adjustments, transfers",
        "pack",
        depends_on=("catalog",),
        permissions={
            "inventory.stock.read": "View stock",
            "inventory.warehouse.manage": "Manage warehouses",
            "inventory.adjustment.create": "Adjust stock",
            "inventory.transfer.manage": "Transfer stock",
        },
        sensitive=("inventory.adjustment.create",),
    ),
    ModuleManifest(
        "procurement",
        "Procurement",
        "Vendors and purchase orders",
        "pack",
        depends_on=("catalog", "inventory", "compliance_gst"),
        permissions={
            "procurement.vendor.read": "View vendors",
            "procurement.vendor.manage": "Manage vendors",
            "procurement.po.read": "View purchase orders",
            "procurement.po.create": "Create purchase orders",
            "procurement.po.approve": "Approve purchase orders",
            "procurement.po.receive": "Receive goods",
        },
    ),
    ModuleManifest(
        "reports",
        "Reporting",
        "Sales, receivables, GST and inventory reports",
        "business",
        permissions={
            "reports.sales.read": "Sales reports",
            "reports.receivables.read": "Receivables reports",
            "reports.inventory.read": "Inventory reports",
        },
    ),
]

MODULES_BY_KEY = {m.key: m for m in MODULES}
TOGGLEABLE_MODULES = [m.key for m in MODULES if m.kind != "core"]

PLATFORM_PERMISSIONS = {
    "platform.tenant.read": "View tenants",
    "platform.tenant.create": "Create, suspend and reactivate tenants",
    "platform.plan.manage": "Manage plans and subscriptions",
    "platform.module.publish": "Publish / withdraw modules",
    "platform.feature_flag.manage": "Manage feature flags and kill switches",
    "platform.override.manage": "Manage tenant feature overrides",
    "platform.telemetry.read": "View system health",
    "platform.user.manage": "Manage platform users",
    "platform.audit.read": "View platform audit log",
    "platform.dlq.replay": "Replay dead-lettered events",
}

PLATFORM_ROLES: dict[str, tuple[str, list[str]]] = {
    "super_admin": ("Super Admin", list(PLATFORM_PERMISSIONS)),
    "ops": (
        "Operations",
        [
            "platform.tenant.read",
            "platform.module.publish",
            "platform.feature_flag.manage",
            "platform.override.manage",
            "platform.telemetry.read",
            "platform.audit.read",
            "platform.dlq.replay",
        ],
    ),
    "engineer": (
        "Engineer",
        ["platform.tenant.read", "platform.telemetry.read", "platform.dlq.replay"],
    ),
    "support": ("Support", ["platform.tenant.read"]),
}


def all_tenant_permissions() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for m in MODULES:
        for k, d in m.permissions.items():
            out[k] = (m.key, d)
    return out


def module_of_permission(perm: str) -> str:
    for m in MODULES:
        if perm in m.permissions:
            return m.key
    raise KeyError(perm)


_ALL = list(all_tenant_permissions())


def _pick(*prefixes: str, exclude: tuple[str, ...] = ()) -> list[str]:
    return [p for p in _ALL if p.startswith(prefixes) and p not in exclude]


_READ_ALL = [p for p in _ALL if p.endswith((".read", ".read_all")) and not p.startswith("core.")]

DEFAULT_ROLES: dict[str, tuple[str, str, list[str]]] = {
    "owner": ("Owner", "Full access, protected role", _ALL),
    "admin": ("Admin", "Manage company, users and all modules", [p for p in _ALL]),
    "sales_manager": (
        "Sales manager",
        "Manage the sales team, CRM and quotations",
        _pick("crm.", "sales.")
        + [
            "catalog.item.read",
            "invoicing.invoice.read",
            "invoicing.note.read",
            "payments.payment.read",
            "inventory.stock.read",
            "reports.sales.read",
            "reports.receivables.read",
            "core.member.read",
        ],
    ),
    "sales_exec": (
        "Sales executive",
        "Own leads, deals, tasks and quotations",
        [
            "crm.lead.read_own",
            "crm.lead.create",
            "crm.lead.update",
            "crm.lead.convert",
            "crm.account.read",
            "crm.account.create",
            "crm.account.update",
            "crm.opportunity.read_own",
            "crm.opportunity.create",
            "crm.opportunity.update",
            "crm.activity.read_own",
            "crm.activity.create",
            "crm.activity.update",
            "catalog.item.read",
            "sales.quotation.read_own",
            "sales.quotation.create",
            "sales.quotation.update",
            "sales.quotation.send",
            "sales.order.read",
            "sales.order.create",
            "inventory.stock.read",
        ],
    ),
    "accounts": (
        "Accounts",
        "Invoices, notes, payments and GST",
        _pick("invoicing.", "payments.")
        + [
            "crm.account.read",
            "catalog.item.read",
            "sales.quotation.read_all",
            "sales.order.read",
            "gst.report.read",
            "reports.receivables.read",
            "reports.sales.read",
            "core.settings.read",
            "procurement.po.read",
            "procurement.vendor.read",
            "inventory.stock.read",
        ],
    ),
    "store_keeper": (
        "Store keeper",
        "Warehouses, stock, transfers and goods receipt",
        _pick("inventory.")
        + [
            "catalog.item.read",
            "sales.order.read",
            "sales.order.update",
            "procurement.po.read",
            "procurement.po.receive",
            "procurement.vendor.read",
            "reports.inventory.read",
        ],
    ),
    "viewer": ("Viewer", "Read-only access to business data", _READ_ALL),
}
