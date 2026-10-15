from datetime import date

from django.contrib.auth.models import Group, User

from caisse.models import PharmacySale
from caisse.tests import Base

from .models import Product, PurchaseOrder, StockMovement


class StockBase(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.pharma = User.objects.create_user("pharma", password="x")
        cls.pharma.groups.add(Group.objects.get(name="Pharmacie"))

    def product(self, name, initial=0, **kwargs):
        p = Product.objects.create(name=name, **kwargs)
        if initial:
            StockMovement.objects.create(product=p, date=date(2026, 10, 1), kind=StockMovement.INITIAL,
                                         quantity=initial)
        return p


class SaleSignalTests(StockBase):
    """Les ventes pharmacie de la journée de caisse mettent le stock à jour."""

    def test_sale_without_product_leaves_stock_alone(self):
        s = self.make_session(date(2026, 10, 2))
        PharmacySale.objects.create(session=s, description="Ventes", quantity=1, unit_price=5000)
        self.assertFalse(StockMovement.objects.exists())

    def test_sale_movement_details(self):
        p = self.product("AMOXICILLINE 500", initial=50, purchase_price=30)
        s = self.make_session(date(2026, 10, 3))
        sale = PharmacySale.objects.create(session=s, product=p, quantity=4, unit_price=75)
        m = sale.movement
        self.assertEqual((m.kind, m.quantity, m.unit_cost, m.date),
                         (StockMovement.SALE, -4, 30, date(2026, 10, 3)))
        self.assertEqual(m.reference, "Caisse du 03/10/2026")

    def test_changing_product_moves_stock_back(self):
        a = self.product("PRODUIT A", initial=20)
        b = self.product("PRODUIT B", initial=20)
        s = self.make_session(date(2026, 10, 4))
        sale = PharmacySale.objects.create(session=s, product=a, quantity=5, unit_price=10)
        sale.product = b
        sale.save()
        self.assertEqual((a.stock_qty, b.stock_qty), (20, 15))
        sale.product = None
        sale.save()
        self.assertEqual((a.stock_qty, b.stock_qty), (20, 20))
        self.assertEqual(StockMovement.objects.filter(kind=StockMovement.SALE).count(), 0)


class InventoryTests(StockBase):
    def post_inventory(self, counts, day="2026-10-15"):
        data = {"date": day, "note": "comptage mensuel"}
        data.update({f"count_{p.id}": v for p, v in counts.items()})
        return self.client.post("/stock/inventaire/", data)

    def test_first_count_is_initial_then_adjustments(self):
        p = self.product("ZINC 20")
        self.client.force_login(self.pharma)
        self.assertEqual(self.post_inventory({p: "120"}).status_code, 302)
        m = p.movements.get()
        self.assertEqual((m.kind, m.quantity), (StockMovement.INITIAL, 120))

        self.post_inventory({p: "113"}, day="2026-10-31")
        adjust = p.movements.get(kind=StockMovement.ADJUST)
        self.assertEqual((adjust.quantity, adjust.date), (-7, date(2026, 10, 31)))
        self.assertEqual(p.stock_qty, 113)

    def test_blank_invalid_and_unchanged_counts_are_ignored(self):
        same = self.product("INCHANGÉ", initial=10)
        blank = self.product("NON COMPTÉ", initial=10)
        bad = self.product("SAISIE ERRONÉE", initial=10)
        self.client.force_login(self.pharma)
        self.post_inventory({same: "10", blank: "", bad: "dix"})
        self.assertEqual(StockMovement.objects.count(), 3)  # seulement les stocks initiaux

    def test_negative_count_is_clamped_to_zero(self):
        p = self.product("GANTS", initial=40)
        self.client.force_login(self.pharma)
        self.post_inventory({p: "-5"})
        self.assertEqual(p.stock_qty, 0)

    def test_inactive_products_are_not_counted(self):
        p = self.product("RETIRÉ", initial=10, active=False)
        self.client.force_login(self.pharma)
        self.post_inventory({p: "0"})
        self.assertEqual(p.stock_qty, 10)


class LossTests(StockBase):
    def test_loss_removes_stock(self):
        p = self.product("SÉRUM SALÉ", initial=30, purchase_price=400)
        self.client.force_login(self.pharma)
        r = self.client.post("/stock/sortie/", {"product": p.id, "quantity": 3, "date": "2026-10-20",
                                                "note": "flacons cassés"})
        self.assertRedirects(r, f"/stock/produit/{p.id}/", fetch_redirect_response=False)
        m = p.movements.get(kind=StockMovement.LOSS)
        self.assertEqual((m.quantity, m.unit_cost, m.note), (-3, 400, "flacons cassés"))
        self.assertEqual(p.stock_qty, 27)

    def test_loss_requires_reason_and_positive_quantity(self):
        p = self.product("COTON", initial=10)
        self.client.force_login(self.pharma)
        self.client.post("/stock/sortie/", {"product": p.id, "quantity": 2, "date": "2026-10-20", "note": ""})
        self.client.post("/stock/sortie/", {"product": p.id, "quantity": 0, "date": "2026-10-20", "note": "x"})
        self.assertFalse(p.movements.filter(kind=StockMovement.LOSS).exists())


class OrderTests(StockBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.pharma)

    def new_order(self, day="2026-10-10"):
        self.client.post("/stock/commandes/nouvelle/", {"date": day, "note": ""})
        return PurchaseOrder.objects.order_by("-id").first()

    def add_line(self, order, product, quantity, unit_cost=""):
        self.client.post(f"/stock/commandes/{order.id}/", {"product": product.id, "quantity": quantity,
                                                            "unit_cost": unit_cost})

    def set_status(self, order, action):
        self.client.post(f"/stock/commandes/{order.id}/statut/", {"action": action})
        order.refresh_from_db()

    def test_numbers_are_sequential_per_year(self):
        numbers = [self.new_order(d).number for d in ("2026-03-01", "2026-04-01", "2027-01-05")]
        self.assertEqual(numbers, ["BC-2026-001", "BC-2026-002", "BC-2027-001"])

    def test_empty_order_cannot_be_placed(self):
        order = self.new_order()
        self.set_status(order, "commander")
        self.assertEqual(order.status, PurchaseOrder.DRAFT)

    def test_line_defaults_to_last_purchase_price(self):
        p = self.product("METRONIDAZOLE", purchase_price=15)
        order = self.new_order()
        self.add_line(order, p, 200)
        self.assertEqual(order.lines.get().unit_cost, 15)
        self.assertEqual(order.total, 3000)

    def test_lines_only_editable_in_draft(self):
        p = self.product("IBUPROFENE", purchase_price=10)
        order = self.new_order()
        self.add_line(order, p, 10)
        self.set_status(order, "commander")
        self.add_line(order, p, 99)
        line = order.lines.get()
        r = self.client.post(f"/stock/commandes/{order.id}/ligne/{line.id}/supprimer/")
        self.assertEqual(r.status_code, 404)
        self.set_status(order, "brouillon")
        self.client.post(f"/stock/commandes/{order.id}/ligne/{line.id}/supprimer/")
        self.assertFalse(order.lines.exists())

    def test_partial_reception(self):
        a = self.product("REÇU", purchase_price=100)
        b = self.product("EN RUPTURE CHEZ LE FOURNISSEUR", purchase_price=200)
        order = self.new_order()
        self.add_line(order, a, 10, 120)
        self.add_line(order, b, 5, 250)
        self.set_status(order, "commander")
        la, lb = order.lines.order_by("id")
        self.client.post(f"/stock/commandes/{order.id}/reception/",
                         {"date": "2026-10-12", f"qty_{la.id}": 10, f"qty_{lb.id}": 0})
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.stock_qty, a.purchase_price), (10, 120))
        self.assertEqual((b.stock_qty, b.purchase_price), (0, 200))  # rien reçu : prix inchangé
        order.refresh_from_db()
        self.assertEqual((order.status, order.received_date), (PurchaseOrder.RECEIVED, date(2026, 10, 12)))

    def test_order_cannot_be_received_twice_or_after_cancel(self):
        p = self.product("PARACETAMOL SIROP", purchase_price=500)
        order = self.new_order()
        self.add_line(order, p, 10)
        self.set_status(order, "commander")
        url = f"/stock/commandes/{order.id}/reception/"
        self.client.post(url, {"date": "2026-10-12"})
        self.assertEqual(self.client.post(url, {"date": "2026-10-13"}).status_code, 404)
        self.assertEqual(p.stock_qty, 10)
        self.set_status(order, "annuler")
        self.assertEqual(order.status, PurchaseOrder.RECEIVED)  # une commande reçue ne s'annule pas

        cancelled = self.new_order()
        self.add_line(cancelled, p, 10)
        self.set_status(cancelled, "commander")
        self.set_status(cancelled, "annuler")
        self.assertEqual(cancelled.status, PurchaseOrder.CANCELLED)
        r = self.client.post(f"/stock/commandes/{cancelled.id}/reception/", {"date": "2026-10-14"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(p.stock_qty, 10)


class ProductListTests(StockBase):
    def test_alert_filter(self):
        self.product("SOUS LE SEUIL", initial=5, reorder_level=10)
        self.product("AU SEUIL", initial=10, reorder_level=10)
        self.product("AU-DESSUS", initial=11, reorder_level=10)
        self.product("SANS SEUIL", initial=0)
        self.product("INACTIF", initial=0, reorder_level=10, active=False)
        self.client.force_login(self.pharma)
        r = self.client.get("/stock/", {"voir": "alerte"})
        names = {p.name for p in r.context["products"]}
        self.assertEqual(names, {"SOUS LE SEUIL", "AU SEUIL"})

    def test_stock_value_ignores_negative_stock(self):
        self.product("POSITIF", initial=10, purchase_price=100)
        neg = self.product("NÉGATIF", purchase_price=100)
        StockMovement.objects.create(product=neg, date=date(2026, 10, 1), kind=StockMovement.LOSS, quantity=-3)
        self.client.force_login(self.pharma)
        self.assertEqual(self.client.get("/stock/").context["stock_value"], 1000)


class PermissionTests(StockBase):
    def test_cashier_can_view_but_not_manage_stock(self):
        p = self.product("VITAMINE C", initial=10, sale_price=25)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get("/stock/").status_code, 200)
        self.assertEqual(self.client.get(f"/stock/produit/{p.id}/").status_code, 200)
        for url in ("/stock/produit/nouveau/", "/stock/commandes/nouvelle/", "/stock/inventaire/",
                    "/stock/sortie/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.post(f"/stock/produit/{p.id}/", {"name": "VITAMINE C", "form": "AUTRE", "unit": "unité",
                                                     "sale_price": 1, "purchase_price": 0, "reorder_level": 0})
        p.refresh_from_db()
        self.assertEqual(p.sale_price, 25)

    def test_supervisor_can_manage_stock(self):
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get("/stock/inventaire/").status_code, 200)


class StockEntryTests(StockBase):
    def test_add_stock_from_product_page(self):
        p = self.product("PARACETAMOL", purchase_price=100)
        self.client.force_login(self.pharma)
        self.assertContains(self.client.get(f"/stock/produit/{p.id}/"), "Ajouter du stock")
        r = self.client.post(f"/stock/produit/{p.id}/entree/", {"quantity": 500, "date": "2026-10-15",
                                                                "unit_cost": 90, "reference": "Facture 12"})
        self.assertRedirects(r, f"/stock/produit/{p.id}/", fetch_redirect_response=False)
        p.refresh_from_db()
        self.assertEqual((p.stock_qty, p.purchase_price), (500, 90))
        m = p.movements.get()
        self.assertEqual((m.kind, m.reference, m.created_by), (StockMovement.ENTRY, "Facture 12", self.pharma))

    def test_donation_keeps_purchase_price(self):
        p = self.product("DON", purchase_price=100)
        self.client.force_login(self.pharma)
        self.client.post(f"/stock/produit/{p.id}/entree/", {"quantity": 20, "date": "2026-10-15", "unit_cost": 0})
        p.refresh_from_db()
        self.assertEqual((p.stock_qty, p.purchase_price), (20, 100))

    def test_invalid_entry_shows_errors_without_saving(self):
        p = self.product("ERREUR", purchase_price=100)
        self.client.force_login(self.pharma)
        r = self.client.post(f"/stock/produit/{p.id}/entree/", {"quantity": 0, "date": "2026-10-15",
                                                                "name": "NE PAS RENOMMER"})
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual((p.name, p.stock_qty), ("ERREUR", 0))

    def test_cashier_cannot_add_stock(self):
        p = self.product("X")
        self.client.force_login(self.cashier)
        self.assertNotContains(self.client.get(f"/stock/produit/{p.id}/"), "Ajouter du stock")
        r = self.client.post(f"/stock/produit/{p.id}/entree/", {"quantity": 5, "date": "2026-10-15"})
        self.assertEqual(r.status_code, 403)

    def test_initial_stock_on_creation(self):
        self.client.force_login(self.pharma)
        self.client.post("/stock/produit/nouveau/", {"name": "AMOXI 500", "form": "COMPRIME", "unit": "gélule",
                                                     "sale_price": 75, "purchase_price": 40, "reorder_level": 50,
                                                     "active": "on", "initial_stock": 300})
        p = Product.objects.get(name="AMOXI 500")
        self.assertEqual(p.stock_qty, 300)
        self.assertEqual(p.movements.get().kind, StockMovement.INITIAL)

    def test_loss_form_prefilled_from_product(self):
        p = self.product("PREREMPLI", initial=5)
        self.client.force_login(self.pharma)
        r = self.client.get("/stock/sortie/", {"produit": p.id})
        self.assertContains(r, f'<option value="{p.id}" selected>')
