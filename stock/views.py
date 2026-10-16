from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log
from core.roles import can, require

from .forms import (InitialStockForm, LossForm, NewProductForm, OrderForm, OrderLineForm, ProductForm,
                    StockEntryForm)
from .models import Product, PurchaseOrder, PurchaseOrderLine, StockMovement


def _products_with_qty():
    return Product.objects.annotate(qty=Sum("movements__quantity"))


@require("pharmacie")
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
    value = sum(p.stock_value(p.qty) for p in products)
    return render(request, "stock/product_list.html", {
        "products": products, "q": q, "show": show, "stock_value": value,
        "can_stock": can(request.user, "stock"),
    })


@require("pharmacie")
def product_detail(request, pk, entry_form=None):
    product = get_object_or_404(_products_with_qty(), pk=pk)
    form = None
    if can(request.user, "stock"):
        posted = request.method == "POST" and entry_form is None  # sinon : POST de l'ajout de stock
        form = ProductForm(request.POST if posted else None, instance=product)
        if posted and form.is_valid():
            form.save()
            messages.success(request, "Produit enregistré.")
            return redirect("product_detail", pk=pk)
        entry_form = entry_form or StockEntryForm(initial={"date": timezone.localdate()}, product=product)
    movements = product.movements.select_related("created_by")[:200]
    return render(request, "stock/product_detail.html", {"product": product, "form": form, "movements": movements,
                                                         "entry_form": entry_form})


@require_POST
@require("stock")
def stock_entry(request, pk):
    """Ajout de stock sans commande : achat direct, don, transfert…"""
    product = get_object_or_404(Product, pk=pk)
    form = StockEntryForm(request.POST, product=product)
    if not form.is_valid():
        return product_detail(request, pk, entry_form=form)
    cost = form.cleaned_data["unit_cost"]  # par unité d'achat (ex. boîte)
    if cost is None:
        cost = product.purchase_price
    packs = form.cleaned_data["quantity"]
    units = packs * product.purchase_size
    StockMovement.objects.create(
        product=product, date=form.cleaned_data["date"], kind=StockMovement.ENTRY,
        quantity=units, unit_cost=round(cost / product.purchase_size),
        reference=form.cleaned_data["reference"], note=form.cleaned_data["note"], created_by=request.user)
    if form.cleaned_data["unit_cost"]:
        product.purchase_price = cost
        product.save(update_fields=["purchase_price"])
    added = f"{packs} {product.purchase_unit}(s) = {units} {product.unit}(s)" if product.purchase_unit         else f"{units} {product.unit}(s)"
    messages.success(request, f"{added} ajouté(s) au stock de « {product.name} ».")
    return redirect("product_detail", pk=pk)


@require("stock")
def product_new(request):
    form = NewProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        p = form.save()
        if form.cleaned_data.get("initial_stock"):
            StockMovement.objects.create(
                product=p, date=timezone.localdate(), kind=StockMovement.INITIAL,
                quantity=form.cleaned_data["initial_stock"], unit_cost=round(p.unit_cost),
                reference="Stock initial (création du produit)", created_by=request.user)
        messages.success(request, f"Produit « {p.name} » créé.")
        return redirect("product_detail", pk=p.pk)
    return render(request, "stock/product_form.html", {"form": form})


# --- Commandes -------------------------------------------------------------
@require("pharmacie")
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


@require("pharmacie")
def order_detail(request, pk):
    order = get_object_or_404(PurchaseOrder.objects.select_related("supplier"), pk=pk)
    editable = order.status == PurchaseOrder.DRAFT and can(request.user, "stock")
    line_form = OrderLineForm() if editable else None
    if request.method == "POST" and editable:
        line_form = OrderLineForm(request.POST)
        if line_form.is_valid():
            line = line_form.save(commit=False)
            line.order = order
            line.units_per_pack = line.product.purchase_size
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
                    # quantité et prix par unité d'achat (boîte) -> unités de stock (comprimés)
                    size = line.units_per_pack or 1
                    StockMovement.objects.create(
                        product=line.product, date=received_date, kind=StockMovement.RECEPTION,
                        quantity=qty * size, unit_cost=round(line.unit_cost / size), reference=order.number,
                        order_line=line, created_by=request.user)
                    if line.unit_cost:
                        line.product.purchase_price = round(line.unit_cost * line.product.purchase_size / size)
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
                        quantity=diff, unit_cost=round(p.unit_cost), reference=f"Inventaire du {day:%d/%m/%Y}",
                        note=note, created_by=request.user)
                    changes += 1
        messages.success(request, f"Inventaire enregistré : {changes} produit(s) ajusté(s).")
        return redirect("product_list")
    return render(request, "stock/inventory.html", {"products": products, "form": form})


@require("stock")
def loss(request):
    form = LossForm(request.POST or None, initial={"date": timezone.localdate(), "product": request.GET.get("produit")})
    if request.method == "POST" and form.is_valid():
        p = form.cleaned_data["product"]
        StockMovement.objects.create(product=p, date=form.cleaned_data["date"], kind=StockMovement.LOSS,
                                     quantity=-form.cleaned_data["quantity"], unit_cost=round(p.unit_cost),
                                     note=form.cleaned_data["note"], reference="Sortie pour perte",
                                     created_by=request.user)
        messages.success(request, "Sortie enregistrée.")
        return redirect("product_detail", pk=p.pk)
    return render(request, "stock/loss.html", {"form": form})
