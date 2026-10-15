from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log
from core.roles import can, require

from .forms import InitialStockForm, LossForm, OrderForm, OrderLineForm, ProductForm
from .models import Product, PurchaseOrder, PurchaseOrderLine, StockMovement


def _products_with_qty():
    return Product.objects.annotate(qty=Sum("movements__quantity"))


def product_list(request):
    qs = _products_with_qty()
    q = request.GET.get("q", "").strip()
    show = request.GET.get("voir", "actifs")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
    if show == "actifs":
        qs = qs.filter(active=True)
    products = list(qs)
    if show == "alerte":
        products = [p for p in products if p.active and p.reorder_level and (p.qty or 0) <= p.reorder_level]
    value = sum((p.qty or 0) * p.purchase_price for p in products if (p.qty or 0) > 0)
    return render(request, "stock/product_list.html", {
        "products": products, "q": q, "show": show, "stock_value": value,
        "can_stock": can(request.user, "stock"),
    })


def product_detail(request, pk):
    product = get_object_or_404(_products_with_qty(), pk=pk)
    form = None
    if can(request.user, "stock"):
        form = ProductForm(request.POST or None, instance=product)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Produit enregistré.")
            return redirect("product_detail", pk=pk)
    movements = product.movements.select_related("created_by")[:200]
    return render(request, "stock/product_detail.html", {"product": product, "form": form, "movements": movements})


@require("stock")
def product_new(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        p = form.save()
        messages.success(request, f"Produit « {p.name} » créé.")
        return redirect("product_detail", pk=p.pk)
    return render(request, "stock/product_form.html", {"form": form})


# --- Commandes -------------------------------------------------------------
def order_list(request):
    orders = PurchaseOrder.objects.select_related("supplier").prefetch_related("lines")
    return render(request, "stock/order_list.html", {"orders": orders, "can_stock": can(request.user, "stock")})


@require("stock")
def order_new(request):
    form = OrderForm(request.POST or None, initial={"date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        order = form.save(commit=False)
        order.number = PurchaseOrder.next_number(order.date)
        order.created_by = request.user
        order.save()
        return redirect("order_detail", pk=order.pk)
    return render(request, "stock/order_form.html", {"form": form})


def order_detail(request, pk):
    order = get_object_or_404(PurchaseOrder.objects.select_related("supplier"), pk=pk)
    editable = order.status == PurchaseOrder.DRAFT and can(request.user, "stock")
    line_form = OrderLineForm() if editable else None
    if request.method == "POST" and editable:
        line_form = OrderLineForm(request.POST)
        if line_form.is_valid():
            line = line_form.save(commit=False)
            line.order = order
            if not line.unit_cost:
                line.unit_cost = line.product.purchase_price
            line.save()
            return redirect("order_detail", pk=pk)
    return render(request, "stock/order_detail.html", {
        "order": order, "lines": order.lines.select_related("product"), "line_form": line_form,
        "editable": editable, "can_stock": can(request.user, "stock"),
    })


@require_POST
@require("stock")
def order_line_delete(request, pk, line_id):
    order = get_object_or_404(PurchaseOrder, pk=pk, status=PurchaseOrder.DRAFT)
    get_object_or_404(PurchaseOrderLine, pk=line_id, order=order).delete()
    return redirect("order_detail", pk=pk)


@require_POST
@require("stock")
def order_status(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    action = request.POST.get("action")
    if action == "commander" and order.status == PurchaseOrder.DRAFT:
        if not order.lines.exists():
            messages.error(request, "La commande est vide.")
        else:
            order.status = PurchaseOrder.ORDERED
            order.save()
            messages.success(request, "Commande passée.")
    elif action == "annuler" and order.status in (PurchaseOrder.DRAFT, PurchaseOrder.ORDERED):
        order.status = PurchaseOrder.CANCELLED
        order.save()
        messages.info(request, "Commande annulée.")
    elif action == "brouillon" and order.status == PurchaseOrder.ORDERED:
        order.status = PurchaseOrder.DRAFT
        order.save()
    return redirect("order_detail", pk=pk)


@require("stock")
def order_receive(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk, status=PurchaseOrder.ORDERED)
    lines = list(order.lines.select_related("product"))
    if request.method == "POST":
        try:
            received_date = timezone.datetime.strptime(request.POST.get("date"), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            received_date = timezone.localdate()
        with transaction.atomic():
            for line in lines:
                try:
                    qty = max(0, int(request.POST.get(f"qty_{line.id}", line.quantity)))
                except ValueError:
                    qty = line.quantity
                line.received_quantity = qty
                line.save()
                if qty:
                    StockMovement.objects.create(
                        product=line.product, date=received_date, kind=StockMovement.RECEPTION, quantity=qty,
                        unit_cost=line.unit_cost, reference=order.number, order_line=line,
                        created_by=request.user)
                    if line.unit_cost:
                        line.product.purchase_price = line.unit_cost
                        line.product.save(update_fields=["purchase_price"])
            order.status = PurchaseOrder.RECEIVED
            order.received_date = received_date
            order.save()
            log("receive", order, {"lignes": {l.product.name: l.received_quantity for l in lines}})
        messages.success(request, "Réception enregistrée : le stock a été mis à jour.")
        return redirect("order_detail", pk=pk)
    return render(request, "stock/order_receive.html", {"order": order, "lines": lines,
                                                        "today": timezone.localdate()})


# --- Inventaire et pertes ----------------------------------------------------
@require("stock")
def inventory(request):
    products = list(_products_with_qty().filter(active=True))
    form = InitialStockForm(request.POST or None, initial={"date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        day = form.cleaned_data["date"]
        note = form.cleaned_data["note"]
        changes = 0
        with transaction.atomic():
            for p in products:
                raw = request.POST.get(f"count_{p.id}", "").strip()
                if raw == "":
                    continue
                try:
                    counted = max(0, int(raw))
                except ValueError:
                    continue
                diff = counted - (p.qty or 0)
                if diff:
                    first = not p.movements.exists()
                    StockMovement.objects.create(
                        product=p, date=day, kind=StockMovement.INITIAL if first else StockMovement.ADJUST,
                        quantity=diff, unit_cost=p.purchase_price, reference=f"Inventaire du {day:%d/%m/%Y}",
                        note=note, created_by=request.user)
                    changes += 1
        messages.success(request, f"Inventaire enregistré : {changes} produit(s) ajusté(s).")
        return redirect("product_list")
    return render(request, "stock/inventory.html", {"products": products, "form": form})


@require("stock")
def loss(request):
    form = LossForm(request.POST or None, initial={"date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        p = form.cleaned_data["product"]
        StockMovement.objects.create(product=p, date=form.cleaned_data["date"], kind=StockMovement.LOSS,
                                     quantity=-form.cleaned_data["quantity"], unit_cost=p.purchase_price,
                                     note=form.cleaned_data["note"], reference="Sortie pour perte",
                                     created_by=request.user)
        messages.success(request, "Sortie enregistrée.")
        return redirect("product_detail", pk=p.pk)
    return render(request, "stock/loss.html", {"form": form})
