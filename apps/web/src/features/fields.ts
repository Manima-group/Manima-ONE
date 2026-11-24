import type { FieldDef } from "@/components/form";
import { label } from "@/lib/format";

export const LEAD_STATUSES = ["new", "contacted", "qualified", "lost"];
export const LEAD_SOURCES = ["manual", "website", "referral", "email", "whatsapp", "event", "form", "import"];

export const LEAD_FIELDS: FieldDef[] = [
  { name: "name", label: "Contact name", required: true },
  { name: "company", label: "Company" },
  { name: "email", label: "Email", type: "email" },
  { name: "phone", label: "Phone", placeholder: "+91…" },
  { name: "source", label: "Source", type: "select", required: true, options: LEAD_SOURCES.map((s) => ({ value: s, label: label(s) })) },
  { name: "status", label: "Status", type: "select", required: true, options: LEAD_STATUSES.map((s) => ({ value: s, label: label(s) })) },
  { name: "estimated_value", label: "Estimated value (₹)", type: "money" },
  { name: "score", label: "Score (0–100)", type: "number" },
  { name: "owner_id", label: "Owner", type: "member", placeholder: "Me" },
  { name: "lost_reason", label: "Lost reason", hidden: (v) => v.status !== "lost", colSpan: 2 },
  { name: "notes", label: "Notes", type: "textarea" },
];


const addr = (prefix: "billing_address" | "shipping_address" | "address", title: string): FieldDef[] => [
  { name: `${prefix}.line1`, path: [prefix, "line1"], label: `${title} – line 1`, colSpan: 2 },
  { name: `${prefix}.city`, path: [prefix, "city"], label: "City" },
  { name: `${prefix}.pincode`, path: [prefix, "pincode"], label: "PIN code" },
];

export const ACCOUNT_FIELDS: FieldDef[] = [
  { name: "name", label: "Customer name", required: true, colSpan: 2 },
  { name: "type", label: "Type", type: "select", required: true, options: ["customer", "prospect", "partner"].map((v) => ({ value: v, label: label(v) })) },
  { name: "gstin", label: "GSTIN", placeholder: "15-character GSTIN", hint: "Leave empty for unregistered (B2C) customers" },
  { name: "state_code", label: "State (place of supply)", type: "state" },
  { name: "pan", label: "PAN" },
  { name: "email", label: "Email", type: "email" },
  { name: "phone", label: "Phone" },
  { name: "payment_terms_days", label: "Payment terms (days)", type: "number" },
  { name: "credit_limit", label: "Credit limit (₹)", type: "money" },
  { name: "owner_id", label: "Account owner", type: "member", placeholder: "Me" },
  { name: "industry", label: "Industry" },
  ...addr("billing_address", "Billing address"),
  { name: "notes", label: "Notes", type: "textarea" },
];

export const CONTACT_FIELDS: FieldDef[] = [
  { name: "name", label: "Name", required: true },
  { name: "account_id", label: "Customer", type: "remote", endpoint: "/crm/accounts" },
  { name: "email", label: "Email", type: "email" },
  { name: "phone", label: "Phone" },
  { name: "designation", label: "Designation" },
  { name: "is_primary", label: "Primary contact", type: "checkbox" },
];

export const GST_RATES = ["0", "0.25", "3", "5", "12", "18", "28", "40"];
export const UNITS = ["nos", "pcs", "kg", "g", "ltr", "ml", "m", "cm", "box", "set", "pack", "hrs", "day", "month", "job", "sqft"];

export const ITEM_FIELDS: FieldDef[] = [
  { name: "sku", label: "SKU / code", required: true },
  { name: "name", label: "Name", required: true },
  { name: "type", label: "Type", type: "select", required: true, options: [{ value: "goods", label: "Goods" }, { value: "service", label: "Service" }] },
  { name: "category", label: "Category" },
  { name: "hsn_sac", label: "HSN / SAC code", hint: "4–8 digits" },
  { name: "gst_rate", label: "GST rate %", type: "select", required: true, options: GST_RATES.map((r) => ({ value: r, label: `${r}%` })) },
  { name: "unit", label: "Unit", type: "select", required: true, options: UNITS.map((u) => ({ value: u, label: u })) },
  { name: "price", label: "Sale price (₹, excl. GST)", type: "money", required: true },
  { name: "purchase_price", label: "Purchase price (₹)", type: "money" },
  { name: "reorder_level", label: "Reorder level", type: "number", hidden: (v) => v.type === "service" },
  { name: "track_stock", label: "Track stock", type: "checkbox", hidden: (v) => v.type === "service" },
  { name: "active", label: "Active", type: "checkbox" },
  { name: "description", label: "Description", type: "textarea" },
];

export const VENDOR_FIELDS: FieldDef[] = [
  { name: "name", label: "Vendor name", required: true, colSpan: 2 },
  { name: "gstin", label: "GSTIN" },
  { name: "state_code", label: "State", type: "state" },
  { name: "contact_person", label: "Contact person" },
  { name: "email", label: "Email", type: "email" },
  { name: "phone", label: "Phone" },
  { name: "payment_terms_days", label: "Payment terms (days)", type: "number" },
  ...addr("address", "Address"),
];

export const WAREHOUSE_FIELDS: FieldDef[] = [
  { name: "name", label: "Name", required: true },
  { name: "code", label: "Code", required: true, hint: "Letters, digits, - and _" },
  { name: "is_default", label: "Default warehouse", type: "checkbox" },
  { name: "active", label: "Active", type: "checkbox" },
  ...addr("address", "Address"),
];

const gstReg: FieldDef = { name: "gst_registration_id", label: "Billing GSTIN", type: "remote", endpoint: "/tenant/gst-registrations",
  optionLabel: (r) => `${r.gstin} · ${r.trade_name ?? r.legal_name}`, placeholder: "Default registration" };
const customer: FieldDef = { name: "account_id", label: "Customer", type: "remote", endpoint: "/crm/accounts", required: true,
  optionLabel: (r) => `${r.name}${r.gstin ? ` · ${r.gstin}` : ""}` };
const pos: FieldDef = { name: "place_of_supply", label: "Place of supply", type: "state", hint: "Defaults to the customer's state" };

export const QUOTE_HEADER: FieldDef[] = [
  customer, gstReg,
  { name: "issue_date", label: "Quote date", type: "date" },
  { name: "valid_until", label: "Valid until", type: "date", hint: "Defaults to company validity days" },
  pos,
  { name: "opportunity_id", label: "Opportunity", type: "remote", endpoint: "/crm/opportunities", placeholder: "None" },
  { name: "terms", label: "Terms & conditions", type: "textarea" },
  { name: "notes", label: "Notes to customer", type: "textarea" },
];

export const ORDER_HEADER: FieldDef[] = [
  customer, gstReg,
  { name: "order_date", label: "Order date", type: "date" },
  { name: "expected_delivery", label: "Expected delivery", type: "date" },
  { name: "warehouse_id", label: "Ship from warehouse", type: "remote", endpoint: "/inventory/warehouses", placeholder: "Default warehouse" },
  { name: "customer_po", label: "Customer PO no." },
  pos,
  { name: "notes", label: "Notes", type: "textarea" },
];

export const SCENARIOS = [
  ["", "Auto (B2B if GSTIN, else B2C)"], ["b2b", "B2B – registered"], ["b2c", "B2C – unregistered"], ["export_with_tax", "Export (with IGST)"],
  ["export_lut", "Export under LUT (zero-rated)"], ["sez_with_tax", "SEZ (with IGST)"], ["sez_lut", "SEZ under LUT"],
];

export const INVOICE_HEADER: FieldDef[] = [
  customer, gstReg,
  { name: "invoice_date", label: "Invoice date", type: "date" },
  { name: "due_date", label: "Due date", type: "date", hint: "Defaults to customer payment terms" },
  { name: "scenario", label: "GST scenario", type: "select", options: SCENARIOS.map(([value, l]) => ({ value, label: l })) },
  pos,
  { name: "recipient_gstin", label: "Recipient GSTIN (override)" },
  { name: "reverse_charge", label: "Reverse charge applies", type: "checkbox" },
  { name: "terms", label: "Terms", type: "textarea" },
  { name: "notes", label: "Notes", type: "textarea" },
];

export const PO_HEADER: FieldDef[] = [
  { name: "vendor_id", label: "Vendor", type: "remote", endpoint: "/procurement/vendors", required: true },
  { name: "warehouse_id", label: "Deliver to warehouse", type: "remote", endpoint: "/inventory/warehouses", placeholder: "Default warehouse" },
  { name: "order_date", label: "PO date", type: "date" },
  { name: "expected_date", label: "Expected delivery", type: "date" },
  { name: "notes", label: "Notes to vendor", type: "textarea" },
];

export const PAYMENT_METHODS = ["upi", "bank_transfer", "cash", "cheque", "card", "netbanking"];
