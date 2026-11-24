"use client";

import { useState } from "react";
import { api, ApiError, type Page } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { Alert, Button, Checkbox, Dialog, Field, Input, Select, Textarea } from "./ui";

type Opt = { value: string; label: string };

export type FieldDef = {
  name: string;
  label: string;
  type?: "text" | "email" | "number" | "money" | "textarea" | "select" | "remote" | "checkbox" | "date" | "datetime" | "state" | "member";
  options?: Opt[];
  endpoint?: string; // remote select: list endpoint ({data:[]} or [])
  optionLabel?: (r: Record<string, unknown>) => string;
  required?: boolean;
  placeholder?: string;
  hint?: string;
  colSpan?: 1 | 2;
  hidden?: (v: Record<string, unknown>) => boolean;
  /** For nested objects like address.city */
  path?: string[];
};

type Values = Record<string, unknown>;

function getIn(v: Values, f: FieldDef) {
  if (!f.path) return v[f.name];
  return f.path.reduce<unknown>((acc, k) => (acc && typeof acc === "object" ? (acc as Values)[k] : undefined), v);
}

function setIn(v: Values, f: FieldDef, val: unknown): Values {
  if (!f.path) return { ...v, [f.name]: val };
  const [head, ...rest] = f.path;
  const inner = { ...((v[head] as Values) ?? {}) };
  let cur = inner;
  rest.slice(0, -1).forEach((k) => {
    cur[k] = { ...((cur[k] as Values) ?? {}) };
    cur = cur[k] as Values;
  });
  cur[rest[rest.length - 1]] = val;
  return { ...v, [head]: inner };
}

export function useStates() {
  return useQuery<{ code: string; name: string }[]>("/gst/states");
}

function RemoteSelect({ f, value, onChange, invalid }: { f: FieldDef; value: string; onChange: (v: string) => void; invalid?: boolean }) {
  const ep = f.type === "member" ? "/tenant/members/options" : f.endpoint!;
  const url = ep.includes("?") ? ep : `${ep}${f.type === "member" ? "" : "?limit=200"}`;
  const { data } = useQuery<Page<Values> | Values[]>(url);
  const rows = Array.isArray(data) ? data : data?.data ?? [];
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)} invalid={invalid} aria-label={f.label}>
      <option value="">{f.placeholder ?? "Select…"}</option>
      {rows.map((r) => (
        <option key={String(r.id)} value={String(r.id)}>
          {f.optionLabel ? f.optionLabel(r) : String(r.name ?? r.id)}
        </option>
      ))}
    </Select>
  );
}

export function FormFields({ fields, values, onChange, errors }: {
  fields: FieldDef[]; values: Values; onChange: (v: Values) => void; errors: Record<string, string>;
}) {
  const { data: states } = useStates();
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {fields.filter((f) => !f.hidden?.(values)).map((f) => {
        const raw = getIn(values, f);
        const val = raw === null || raw === undefined ? "" : String(raw);
        const err = errors[f.path ? f.path.join(".") : f.name];
        const set = (x: unknown) => onChange(setIn(values, f, x));
        const span = f.colSpan === 2 || f.type === "textarea" ? "sm:col-span-2" : "";
        if (f.type === "checkbox")
          return (
            <div key={f.name} className={span}>
              <Checkbox label={f.label} checked={!!raw} onChange={(e) => set(e.target.checked)} />
            </div>
          );
        let input: React.ReactNode;
        switch (f.type) {
          case "textarea":
            input = <Textarea value={val} onChange={(e) => set(e.target.value)} placeholder={f.placeholder} invalid={!!err} />;
            break;
          case "select":
            input = (
              <Select value={val} onChange={(e) => set(e.target.value)} invalid={!!err}>
                {!f.required && <option value="">—</option>}
                {f.options!.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
            );
            break;
          case "state":
            input = (
              <Select value={val} onChange={(e) => set(e.target.value || null)} invalid={!!err}>
                <option value="">Select state…</option>
                {(states ?? []).map((s) => <option key={s.code} value={s.code}>{s.code} – {s.name}</option>)}
              </Select>
            );
            break;
          case "remote":
          case "member":
            input = <RemoteSelect f={f} value={val} onChange={(x) => set(x || null)} invalid={!!err} />;
            break;
          case "number":
          case "money":
            input = <Input type="number" step={f.type === "money" ? "0.01" : "any"} value={val} placeholder={f.placeholder}
              onChange={(e) => set(e.target.value)} invalid={!!err} />;
            break;
          case "date":
            input = <Input type="date" value={val.slice(0, 10)} onChange={(e) => set(e.target.value || null)} invalid={!!err} />;
            break;
          case "datetime":
            input = <Input type="datetime-local" value={val.slice(0, 16)} onChange={(e) => set(e.target.value || null)} invalid={!!err} />;
            break;
          default:
            input = <Input type={f.type === "email" ? "email" : "text"} value={val} placeholder={f.placeholder}
              onChange={(e) => set(e.target.value)} invalid={!!err} />;
        }
        return (
          <Field key={f.name} label={f.label} required={f.required} error={err} hint={f.hint} className={span}>
            {input}
          </Field>
        );
      })}
    </div>
  );
}

/** Cleans values: '' -> null for optional fields, keeps numbers as strings (decimal-safe). */
export function clean(values: Values, fields: FieldDef[]): Values {
  const out: Values = { ...values };
  for (const f of fields) {
    if (f.path) continue;
    if (out[f.name] === "") out[f.name] = null;
    if ((f.type === "datetime") && out[f.name]) out[f.name] = new Date(out[f.name] as string).toISOString();
  }
  return out;
}

type FormDialogProps = {
  open: boolean; onClose: () => void; title: string; fields: FieldDef[]; initial: Values;
  submit: (v: Values) => Promise<unknown>; submitLabel?: string; wide?: boolean;
};

export function FormDialog(props: FormDialogProps) {
  // Mounting the body only while open gives every opening a fresh form seeded from `initial`.
  return props.open ? <FormDialogBody {...props} /> : null;
}

function FormDialogBody({ open, onClose, title, fields, initial, submit, submitLabel = "Save", wide }: FormDialogProps) {
  const [values, setValues] = useState<Values>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e?: React.FormEvent) {
    e?.preventDefault();
    const missing: Record<string, string> = {};
    for (const f of fields) {
      const v = getIn(values, f);
      if (f.required && !f.hidden?.(values) && (v === undefined || v === null || v === "")) missing[f.name] = "Required";
    }
    if (Object.keys(missing).length) {
      setErrors(missing);
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await submit(clean(values, fields));
      onClose();
    } catch (err) {
      const ae = err as ApiError;
      setErrors(ae.fieldErrors?.() ?? {});
      setFormError(ae.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={title} wide={wide}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => onSubmit()} loading={busy}>{submitLabel}</Button>
      </>}>
      <form onSubmit={onSubmit} className="space-y-4">
        {formError && <Alert tone="red">{formError}</Alert>}
        <FormFields fields={fields} values={values} onChange={setValues} errors={errors} />
        <button type="submit" className="hidden" />
      </form>
    </Dialog>
  );
}

export function useRemoteSave<T>(base: string) {
  return {
    create: (v: Values) => api.post<T>(base, v),
    update: (id: string, v: Values) => api.patch<T>(`${base}/${id}`, v),
    remove: (id: string) => api.del(`${base}/${id}`),
  };
}
