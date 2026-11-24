"""Reporting: role-aware dashboards, sales, receivables ageing, GST summary (GSTR-1 style), inventory valuation."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, select

from manima.core.security import Ctx, require, tenant_ctx
from manima.modules.catalog.module import Item
from manima.modules.crm.module import Activity, Lead, Opportunity, PipelineStage
from manima.modules.inventory.module import StockBalance
from manima.modules.invoicing.module import AdjustmentNote, Invoice, InvoiceLine
from manima.modules.procurement.module import PurchaseOrder
from manima.modules.sales.module import Quotation, SalesOrder
from manima.shared.money import ZERO

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _months_back(n: int) -> list[date]:
    cur = _month_start(date.today())
    out = []
    for _ in range(n):
        out.append(cur)
        cur = _month_start(cur - timedelta(days=1))
    return list(reversed(out))


def _issued(tenant_id):
    return and_(Invoice.tenant_id == tenant_id, Invoice.document_status == "issued")


def _ageing(db, tenant_id, account_id=None) -> dict:
    today = date.today()
    days = func.greatest(0, today - Invoice.due_date)
    buckets = {
        "current": Invoice.due_date >= today,
        "d1_30": and_(days >= 1, days <= 30),
        "d31_60": and_(days > 30, days <= 60),
        "d61_90": and_(days > 60, days <= 90),
        "d90_plus": days > 90,
    }
    cols = [
        func.coalesce(func.sum(case((cond, Invoice.amount_due), else_=0)), 0).label(k)
        for k, cond in buckets.items()
    ]
    q = select(*cols).where(_issued(tenant_id), Invoice.amount_due > 0)
    if account_id:
        q = q.where(Invoice.account_id == account_id)
    row = db.execute(q).one()
    out = {k: getattr(row, k) for k in buckets}
    out["total"] = sum(out.values(), ZERO)
    out["overdue"] = out["total"] - out["current"]
    return out


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(tenant_ctx)):
    """Sections are included only when the user holds the matching read permission."""
    db, tid = ctx.db, ctx.tenant_id
    today = date.today()
    ms = _month_start(today)
    out: dict = {"generated_at": datetime.now(UTC)}

    if ctx.has("reports.sales.read") or ctx.has("invoicing.invoice.read"):
        months = _months_back(6)
        rows = {
            (k.year, k.month): v
            for k, v in db.execute(
                select(
                    func.date_trunc("month", Invoice.invoice_date).label("m"), func.sum(Invoice.grand_total)
                )
                .where(_issued(tid), Invoice.invoice_date >= months[0])
                .group_by("m")
            ).all()
        }
        trend = [{"month": m.strftime("%b %Y"), "total": rows.get((m.year, m.month), ZERO)} for m in months]
        out["sales"] = {
            "this_month": db.scalar(
                select(func.coalesce(func.sum(Invoice.grand_total), 0)).where(
                    _issued(tid), Invoice.invoice_date >= ms
                )
            ),
            "invoices_this_month": db.scalar(
                select(func.count()).where(_issued(tid), Invoice.invoice_date >= ms)
            ),
            "trend": trend,
        }
    if ctx.has("reports.receivables.read") or ctx.has("invoicing.invoice.read"):
        out["receivables"] = _ageing(db, tid)
    if ctx.has("sales.quotation.read_all") or ctx.has("sales.quotation.read_own"):
        q = select(func.count(), func.coalesce(func.sum(Quotation.grand_total), 0)).where(
            Quotation.tenant_id == tid, Quotation.status == "sent"
        )
        if ctx.own_only("sales.quotation"):
            q = q.where(Quotation.owner_id == ctx.user.id)
        c, v = db.execute(q).one()
        decided = db.execute(
            select(
                func.count().filter(Quotation.status.in_(("accepted", "converted"))),
                func.count().filter(Quotation.status.in_(("accepted", "converted", "rejected"))),
            ).where(Quotation.tenant_id == tid)
        ).one()
        pending_approval = db.scalar(
            select(func.count()).where(
                Quotation.tenant_id == tid,
                Quotation.approval_status == "pending",
                Quotation.status == "draft",
            )
        )
        out["quotations"] = {
            "open_count": c,
            "open_value": v,
            "pending_approval": pending_approval,
            "win_rate": round(decided[0] * 100 / decided[1], 1) if decided[1] else None,
        }
    if ctx.has("crm.lead.read_all") or ctx.has("crm.lead.read_own"):
        q = select(Lead.status, func.count()).where(Lead.tenant_id == tid, Lead.deleted_at.is_(None))
        if ctx.own_only("crm.lead"):
            q = q.where(Lead.owner_id == ctx.user.id)
        out["leads"] = {
            "by_status": dict(db.execute(q.group_by(Lead.status)).all()),
            "new_this_month": db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == tid,
                    Lead.created_at >= ms,
                    Lead.deleted_at.is_(None),
                    *([Lead.owner_id == ctx.user.id] if ctx.own_only("crm.lead") else []),
                )
            ),
        }
    if ctx.has("crm.opportunity.read_all") or ctx.has("crm.opportunity.read_own"):
        q = (
            select(
                PipelineStage.name,
                PipelineStage.position,
                func.count(Opportunity.id),
                func.coalesce(func.sum(Opportunity.value), 0),
            )
            .join(
                Opportunity,
                and_(Opportunity.stage_id == PipelineStage.id, Opportunity.deleted_at.is_(None)),
                isouter=True,
            )
            .where(PipelineStage.tenant_id == tid, PipelineStage.outcome == "open")
        )
        if ctx.own_only("crm.opportunity"):
            q = q.where((Opportunity.owner_id == ctx.user.id) | (Opportunity.id.is_(None)))
        rows = db.execute(q.group_by(PipelineStage.id).order_by(PipelineStage.position)).all()
        out["pipeline"] = [{"stage": r[0], "count": r[2], "value": r[3]} for r in rows]
    if ctx.has("inventory.stock.read"):
        stock_value = db.scalar(
            select(func.coalesce(func.sum(StockBalance.on_hand * Item.purchase_price), 0))
            .join(Item, Item.id == StockBalance.item_id)
            .where(StockBalance.tenant_id == tid)
        )
        sub = (
            select(Item.id, Item.reorder_level, func.coalesce(func.sum(StockBalance.on_hand), 0).label("oh"))
            .outerjoin(StockBalance, StockBalance.item_id == Item.id)
            .where(
                Item.tenant_id == tid,
                Item.track_stock.is_(True),
                Item.deleted_at.is_(None),
                Item.active.is_(True),
            )
            .group_by(Item.id)
            .subquery()
        )
        low = db.scalar(select(func.count()).select_from(sub).where(sub.c.oh <= sub.c.reorder_level))
        out["inventory"] = {
            "stock_value": Decimal(stock_value).quantize(Decimal("0.01")),
            "low_stock_items": low,
        }
    if ctx.has("procurement.po.read"):
        c, v = db.execute(
            select(func.count(), func.coalesce(func.sum(PurchaseOrder.grand_total), 0)).where(
                PurchaseOrder.tenant_id == tid,
                PurchaseOrder.status.in_(("approved", "sent", "partially_received")),
            )
        ).one()
        out["procurement"] = {
            "open_po_count": c,
            "open_po_value": v,
            "pending_approval": db.scalar(
                select(func.count()).where(
                    PurchaseOrder.tenant_id == tid, PurchaseOrder.status == "pending_approval"
                )
            ),
        }
    if ctx.has("sales.order.read"):
        out["orders"] = dict(
            db.execute(
                select(SalesOrder.status, func.count())
                .where(SalesOrder.tenant_id == tid)
                .group_by(SalesOrder.status)
            ).all()
        )
    if ctx.has("crm.activity.read_all") or ctx.has("crm.activity.read_own"):
        base = and_(
            Activity.tenant_id == tid,
            Activity.deleted_at.is_(None),
            Activity.assigned_to == ctx.user.id,
            Activity.type == "task",
            Activity.done_at.is_(None),
        )
        out["my_tasks"] = {
            "open": db.scalar(select(func.count()).where(base)),
            "overdue": db.scalar(select(func.count()).where(base, Activity.due_at < datetime.now(UTC))),
            "due_today": db.scalar(select(func.count()).where(base, func.date(Activity.due_at) == today)),
        }
    return out


@router.get("/sales")
def sales_report(
    date_from: date | None = None,
    date_to: date | None = None,
    group: str = "month",
    ctx: Ctx = Depends(require("reports.sales.read")),
):
    db, tid = ctx.db, ctx.tenant_id
    date_to = date_to or date.today()
    date_from = date_from or _month_start(date_to - timedelta(days=150))
    base = and_(_issued(tid), Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
    if group == "customer":
        rows = db.execute(
            select(
                Invoice.recipient_name,
                func.count(),
                func.sum(Invoice.taxable_total),
                func.sum(Invoice.tax_total),
                func.sum(Invoice.grand_total),
            )
            .where(base)
            .group_by(Invoice.recipient_name)
            .order_by(func.sum(Invoice.grand_total).desc())
        ).all()
        data = [{"label": r[0], "count": r[1], "taxable": r[2], "tax": r[3], "total": r[4]} for r in rows]
    elif group == "item":
        rows = db.execute(
            select(
                InvoiceLine.description,
                func.sum(InvoiceLine.qty),
                func.sum(InvoiceLine.taxable_value),
                func.sum(InvoiceLine.total),
            )
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(base)
            .group_by(InvoiceLine.description)
            .order_by(func.sum(InvoiceLine.total).desc())
        ).all()
        data = [{"label": r[0], "qty": r[1], "taxable": r[2], "total": r[3]} for r in rows]
    else:
        m = func.date_trunc("month", Invoice.invoice_date)
        rows = db.execute(
            select(
                m,
                func.count(),
                func.sum(Invoice.taxable_total),
                func.sum(Invoice.tax_total),
                func.sum(Invoice.grand_total),
            )
            .where(base)
            .group_by(m)
            .order_by(m)
        ).all()
        data = [
            {"label": r[0].strftime("%b %Y"), "count": r[1], "taxable": r[2], "tax": r[3], "total": r[4]}
            for r in rows
        ]
    totals = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Invoice.taxable_total), 0),
            func.coalesce(func.sum(Invoice.tax_total), 0),
            func.coalesce(func.sum(Invoice.grand_total), 0),
        ).where(base)
    ).one()
    return {
        "date_from": date_from,
        "date_to": date_to,
        "group": group,
        "data": data,
        "totals": {"count": totals[0], "taxable": totals[1], "tax": totals[2], "total": totals[3]},
    }


@router.get("/receivables")
def receivables(ctx: Ctx = Depends(require("reports.receivables.read"))):
    db, tid = ctx.db, ctx.tenant_id
    today = date.today()
    days = func.greatest(0, today - Invoice.due_date)
    rows = db.execute(
        select(
            Invoice.account_id,
            Invoice.recipient_name,
            func.count(),
            func.sum(Invoice.amount_due),
            func.sum(case((Invoice.due_date >= today, Invoice.amount_due), else_=0)),
            func.sum(case((and_(days >= 1, days <= 30), Invoice.amount_due), else_=0)),
            func.sum(case((and_(days > 30, days <= 60), Invoice.amount_due), else_=0)),
            func.sum(case((and_(days > 60, days <= 90), Invoice.amount_due), else_=0)),
            func.sum(case((days > 90, Invoice.amount_due), else_=0)),
        )
        .where(_issued(tid), Invoice.amount_due > 0)
        .group_by(Invoice.account_id, Invoice.recipient_name)
        .order_by(func.sum(Invoice.amount_due).desc())
    ).all()
    data = [
        {
            "account_id": r[0],
            "customer": r[1],
            "invoices": r[2],
            "total": r[3],
            "current": r[4],
            "d1_30": r[5],
            "d31_60": r[6],
            "d61_90": r[7],
            "d90_plus": r[8],
        }
        for r in rows
    ]
    return {"summary": _ageing(db, tid), "data": data}


def _gst_data(db, tid, date_from: date, date_to: date) -> dict:
    base = and_(_issued(tid), Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
    b2b = [
        {
            "number": i.number,
            "date": i.invoice_date,
            "gstin": i.recipient_gstin,
            "name": i.recipient_name,
            "pos": i.place_of_supply,
            "reverse_charge": i.reverse_charge,
            "taxable": i.taxable_total,
            "igst": i.igst_total,
            "cgst": i.cgst_total,
            "sgst": i.sgst_total,
            "cess": i.cess_total,
            "total": i.grand_total,
        }
        for i in db.scalars(
            select(Invoice).where(base, Invoice.recipient_gstin.is_not(None)).order_by(Invoice.invoice_date)
        )
    ]
    b2c_rows = db.execute(
        select(
            Invoice.place_of_supply,
            InvoiceLine.gst_rate,
            func.sum(InvoiceLine.taxable_value),
            func.sum(InvoiceLine.igst),
            func.sum(InvoiceLine.cgst),
            func.sum(InvoiceLine.sgst),
            func.sum(InvoiceLine.cess),
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(base, Invoice.recipient_gstin.is_(None))
        .group_by(Invoice.place_of_supply, InvoiceLine.gst_rate)
        .order_by(Invoice.place_of_supply)
    ).all()
    b2c = [
        {"pos": r[0], "rate": r[1], "taxable": r[2], "igst": r[3], "cgst": r[4], "sgst": r[5], "cess": r[6]}
        for r in b2c_rows
    ]
    hsn_rows = db.execute(
        select(
            InvoiceLine.hsn_sac,
            InvoiceLine.unit,
            InvoiceLine.gst_rate,
            func.sum(InvoiceLine.qty),
            func.sum(InvoiceLine.taxable_value),
            func.sum(InvoiceLine.igst),
            func.sum(InvoiceLine.cgst),
            func.sum(InvoiceLine.sgst),
            func.sum(InvoiceLine.total),
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(base)
        .group_by(InvoiceLine.hsn_sac, InvoiceLine.unit, InvoiceLine.gst_rate)
        .order_by(InvoiceLine.hsn_sac)
    ).all()
    hsn = [
        {
            "hsn": r[0],
            "unit": r[1],
            "rate": r[2],
            "qty": r[3],
            "taxable": r[4],
            "igst": r[5],
            "cgst": r[6],
            "sgst": r[7],
            "total": r[8],
        }
        for r in hsn_rows
    ]
    notes = [
        {
            "type": n.note_type,
            "number": n.number,
            "date": n.note_date,
            "taxable": n.taxable_total,
            "igst": n.igst_total,
            "cgst": n.cgst_total,
            "sgst": n.sgst_total,
            "total": n.grand_total,
        }
        for n in db.scalars(
            select(AdjustmentNote).where(
                AdjustmentNote.tenant_id == tid,
                AdjustmentNote.document_status == "issued",
                AdjustmentNote.note_date >= date_from,
                AdjustmentNote.note_date <= date_to,
            )
        )
    ]
    tot = db.execute(
        select(
            func.coalesce(func.sum(Invoice.taxable_total), 0),
            func.coalesce(func.sum(Invoice.igst_total), 0),
            func.coalesce(func.sum(Invoice.cgst_total), 0),
            func.coalesce(func.sum(Invoice.sgst_total), 0),
            func.coalesce(func.sum(Invoice.cess_total), 0),
            func.count(),
        ).where(base)
    ).one()
    return {
        "date_from": date_from,
        "date_to": date_to,
        "b2b": b2b,
        "b2c": b2c,
        "hsn": hsn,
        "notes": notes,
        "totals": {
            "taxable": tot[0],
            "igst": tot[1],
            "cgst": tot[2],
            "sgst": tot[3],
            "cess": tot[4],
            "invoices": tot[5],
        },
    }


@router.get("/gst-summary")
def gst_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    format: str = "json",
    section: str = "b2b",
    ctx: Ctx = Depends(require("gst.report.read")),
):
    date_to = date_to or date.today()
    date_from = date_from or _month_start(date_to)
    data = _gst_data(ctx.db, ctx.tenant_id, date_from, date_to)
    if format != "csv":
        return data
    rows = data.get(section, [])
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    fname = f"gstr1-{section}-{date_from}-{date_to}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/inventory")
def inventory_report(ctx: Ctx = Depends(require("reports.inventory.read", "inventory.stock.read"))):
    db, tid = ctx.db, ctx.tenant_id
    rows = db.execute(
        select(
            Item.category,
            func.count(func.distinct(Item.id)),
            func.coalesce(func.sum(StockBalance.on_hand), 0),
            func.coalesce(func.sum(StockBalance.on_hand * Item.purchase_price), 0),
        )
        .outerjoin(StockBalance, StockBalance.item_id == Item.id)
        .where(Item.tenant_id == tid, Item.track_stock.is_(True), Item.deleted_at.is_(None))
        .group_by(Item.category)
        .order_by(Item.category)
    ).all()
    return {
        "by_category": [
            {"category": r[0] or "Uncategorised", "items": r[1], "qty": r[2], "value": r[3]} for r in rows
        ]
    }
