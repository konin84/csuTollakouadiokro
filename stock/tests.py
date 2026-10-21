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


class ProductSearchTests(StockBase):
    def test_search_filters_the_list_and_htmx_gets_the_same_page(self):
        self.product("PARACETAMOL 500")
        self.product("AMOXICILLINE 500")
        self.client.force_login(self.pharma)
        page = self.client.get("/stock/")
        self.assertContains(page, 'hx-select="#products"')
        r = self.client.get("/stock/?q=para&voir=actifs", HTTP_HX_REQUEST="true")
        self.assertContains(r, 'id="products"')
        self.assertContains(r, "PARACETAMOL 500")
        self.assertNotContains(r, "AMOXICILLINE 500")
        self.assertContains(self.client.get("/stock/?q=zzz"), "Aucun produit ne correspond")


class PermissionTests(StockBase):
    def test_cashier_does_not_see_pharmacy(self):
        p = self.product("VITAMINE C", initial=10, sale_price=25, reorder_level=50)
        self.client.force_login(self.cashier)
        for url in ("/stock/", f"/stock/produit/{p.id}/", "/stock/commandes/", "/stock/produit/nouveau/",
                    "/stock/commandes/nouvelle/", "/stock/inventaire/", "/stock/sortie/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.post(f"/stock/produit/{p.id}/", {"name": "VITAMINE C", "form": "AUTRE", "unit": "unité",
                                                     "sale_price": 1, "purchase_price": 0, "reorder_level": 0})
        p.refresh_from_db()
        self.assertEqual(p.sale_price, 25)
        home = self.client.get("/")
        self.assertNotContains(home, 'href="/stock/')
        self.assertNotContains(home, "Stock sous le seuil")
        self.assertContains(home, 'href="/caisse/"')

    def test_cashier_still_sells_products_at_the_till(self):
        p = self.product("VITAMINE C", initial=10, sale_price=25)
        s = self.make_session(date(2026, 10, 2))
        self.client.force_login(self.cashier)
        self.client.post("/caisse/2026-10-02/vente-pharmacie/", {"patient_name": "", "phone": "", "sex": "", "age": "",
                                                                  "product": [p.id], "product_qty": [2],
                                                                  "product_unit": ["unite"]})
        self.assertEqual(PharmacySale.objects.get(session=s).quantity, 2)
        page = self.client.get("/caisse/2026-10-02/")
        self.assertContains(page, "VITAMINE C")
        self.assertNotContains(page, f'href="/stock/produit/{p.id}/"')

    def test_pharmacy_does_not_see_cash(self):
        s = self.make_session(date(2026, 10, 2))
        self.client.force_login(self.pharma)
        for url in ("/caisse/", "/caisse/aujourdhui/", "/caisse/2026-10-02/", "/versements/",
                    "/caisse/patients/recherche/?q=kon", "/caisse/2026-10-02/patient/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        p = self.product("VITAMINE C", initial=10, sale_price=25)
        self.assertEqual(self.client.post("/caisse/2026-10-02/vente-pharmacie/", {
            "patient_name": "", "product": [p.id], "product_qty": [1], "product_unit": ["unite"]}).status_code, 403)
        self.assertFalse(PharmacySale.objects.filter(session=s).exists())
        home = self.client.get("/")
        self.assertNotContains(home, 'href="/caisse/')
        self.assertNotContains(home, 'href="/versements/')
        self.assertNotContains(home, "Argent en caisse")
        self.assertContains(home, "Stock sous le seuil")
        self.assertContains(home, 'href="/stock/"')

    def test_pharmacy_only_sees_the_stock_report(self):
        self.client.force_login(self.pharma)
        for url in ("/rapports/mensuel/", "/rapports/mensuel/excel/", "/rapports/annuel/", "/rapports/annuel/excel/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.get("/rapports/stock/").status_code, 200)
        home = self.client.get("/")
        self.assertNotContains(home, 'href="/rapports/mensuel/"')
        self.assertNotContains(home, 'href="/rapports/annuel/"')
        self.assertContains(home, 'href="/rapports/stock/"')

    def test_supervisor_sees_stock_report_but_not_pharmacy_pages(self):
        p = self.product("VITAMINE C", initial=10)
        self.client.force_login(self.boss)
        for url in ("/stock/", f"/stock/produit/{p.id}/", "/stock/commandes/", "/stock/inventaire/",
                    "/parametres/fournisseurs/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        home = self.client.get("/")
        self.assertNotContains(home, ">Pharmacie</div>")
        self.assertNotContains(home, 'href="/stock/')
        self.assertContains(home, 'href="/rapports/stock/"')
        report = self.client.get("/rapports/stock/")
        self.assertContains(report, "VITAMINE C")
        self.assertNotContains(report, f'href="/stock/produit/{p.id}/"')


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
        self.assertEqual(self.client.get(f"/stock/produit/{p.id}/").status_code, 403)
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


class StockReportTests(StockBase):
    def setUp(self):
        super().setUp()
        self.p = self.product("AMOXI 500", sale_price=75, purchase_price=40, reorder_level=150)
        move = lambda day, kind, qty: StockMovement.objects.create(product=self.p, date=day, kind=kind, quantity=qty)
        move(date(2026, 9, 20), StockMovement.INITIAL, 200)
        move(date(2026, 9, 25), StockMovement.SALE, -20)                 # avant le mois : dans le stock début
        move(date(2026, 10, 3), StockMovement.RECEPTION, 50)
        PharmacySale.objects.create(session=self.make_session(date(2026, 10, 5)), product=self.p, quantity=80,
                                    unit_price=75)                       # sortie de stock par le signal
        move(date(2026, 10, 8), StockMovement.LOSS, -6)
        move(date(2026, 10, 30), StockMovement.ADJUST, -2)
        move(date(2026, 11, 2), StockMovement.SALE, -10)                 # après le mois : ignoré

    def test_movements_by_product(self):
        self.client.force_login(self.pharma)
        r = self.client.get("/rapports/stock/?mois=2026-10")
        self.assertEqual(r.status_code, 200)
        row = next(x for x in r.context["rows"] if x["product"] == self.p)
        self.assertEqual({k: row[k] for k in ("opening", "entries", "sold", "lost", "adjusted", "closing")},
                         {"opening": 180, "entries": 50, "sold": 80, "lost": 6, "adjusted": -2, "closing": 142})
        self.assertEqual((row["sales_value"], row["lost_value"], row["closing_value"]), (6000, 240, 5680))
        self.assertIn(row, r.context["low"])  # 142 ≤ seuil de 150
        self.assertEqual(len(r.context["entries"]), 1)
        self.assertEqual(len(r.context["losses"]), 1)
        self.assertEqual(len(r.context["adjustments"]), 1)

    def test_each_detail_has_its_own_view(self):
        self.client.force_login(self.pharma)
        page = self.client.get("/rapports/stock/?mois=2026-10")
        self.assertContains(page, "Mouvements par produit")
        self.assertNotContains(page, "<h2>Entrées du mois</h2>")
        self.assertContains(page, 'href="?mois=2026-10&vue=entries"')
        r = self.client.get("/rapports/stock/?mois=2026-10&vue=entries")
        self.assertContains(r, "<h2>Entrées du mois</h2>")
        self.assertContains(r, "Réception commande")
        self.assertNotContains(r, "Mouvements par produit")
        self.assertContains(r, 'href="?mois=2026-11&vue=entries"')          # le mois suivant garde la vue
        self.assertContains(self.client.get("/rapports/stock/?mois=2026-10&vue=losses"), "<h2>Pertes (périmés, casse)</h2>")
        self.assertContains(self.client.get("/rapports/stock/?mois=2026-10&vue=adjustments"), "<h2>Ajustements d")
        self.assertContains(self.client.get("/rapports/stock/?mois=2026-10&vue=nimporte"), "Mouvements par produit")

    def test_excel_export(self):
        self.client.force_login(self.pharma)
        r = self.client.get("/rapports/stock/excel/?mois=2026-10")
        self.assertEqual(r.status_code, 200)
        self.assertIn("rapport-stock-2026-10.xlsx", r["Content-Disposition"])

    def test_access(self):
        self.client.force_login(self.pharma)
        self.assertContains(self.client.get("/"), 'href="/rapports/stock/"')
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get("/rapports/stock/").status_code, 200)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get("/rapports/stock/").status_code, 403)
        self.assertEqual(self.client.get("/rapports/stock/excel/").status_code, 403)
        self.assertNotContains(self.client.get("/"), 'href="/rapports/stock/"')


class PackagingTests(StockBase):
    """Paracétamol : acheté par boîte de 100 comprimés, vendu par plaquette de 10 ou au comprimé."""

    def setUp(self):
        super().setUp()
        self.p = Product.objects.create(name="PARACETAMOL 500", unit="comprimé", sale_price=25,
                                        pack_unit="plaquette", pack_size=10, pack_price=200,
                                        purchase_unit="boîte", purchase_size=100, purchase_price=1500)

    def test_direct_entry_in_boxes(self):
        self.client.force_login(self.pharma)
        page = self.client.get(f"/stock/produit/{self.p.id}/")
        self.assertContains(page, "Nombre de boîtes (100 comprimés)")
        r = self.client.post(f"/stock/produit/{self.p.id}/entree/", {"quantity": 3, "date": "2026-10-15"},
                             follow=True)
        self.assertContains(r, "3 boîte(s) = 300 comprimé(s)")
        self.assertEqual(self.p.stock_qty, 300)
        self.assertEqual(self.p.movements.get().unit_cost, 15)      # 1 500 F / 100 comprimés
        self.assertEqual(self.p.stock_value(300), 4500)

    def test_order_and_reception_in_boxes(self):
        self.client.force_login(self.pharma)
        self.client.post("/stock/commandes/nouvelle/", {"date": "2026-10-10", "note": ""})
        order = PurchaseOrder.objects.get()
        self.client.post(f"/stock/commandes/{order.id}/", {"product": self.p.id, "quantity": 2, "unit_cost": 1600})
        line = order.lines.get()
        self.assertEqual((line.units_per_pack, line.total), (100, 3200))
        self.client.post(f"/stock/commandes/{order.id}/statut/", {"action": "commander"})
        self.client.post(f"/stock/commandes/{order.id}/reception/", {"date": "2026-10-12", f"qty_{line.id}": 2})
        self.p.refresh_from_db()
        self.assertEqual((self.p.stock_qty, self.p.purchase_price), (200, 1600))

    def test_receipt_sells_blisters_and_tablets(self):
        StockMovement.objects.create(product=self.p, date=date(2026, 10, 1), kind=StockMovement.INITIAL,
                                     quantity=100)
        self.make_session(date(2026, 10, 15))
        self.client.force_login(self.cashier)
        data = {"patient_name": "YAO Koffi", "phone": "", "sex": "M", "age": "40",
                "act": [], "act_qty": [], "act_amount": [],
                "product": [self.p.id, self.p.id], "product_qty": [2, 5], "product_unit": ["pack", "unite"]}
        r = self.client.post("/caisse/2026-10-15/patient/", data, follow=True)
        self.assertContains(r, "PARACETAMOL 500 (plaquette)")
        self.assertEqual(self.p.stock_qty, 75)                      # 100 − 2 × 10 − 5
        sales = {s.pack: (s.quantity, s.unit_price, s.amount) for s in PharmacySale.objects.all()}
        self.assertEqual(sales, {True: (2, 200, 400), False: (5, 25, 125)})
        # 8 plaquettes = 80 comprimés > 75 en stock
        data.update(product=[self.p.id], product_qty=[8], product_unit=["pack"], patient_name="KONE Awa")
        r = self.client.post("/caisse/2026-10-15/patient/", data)
        self.assertContains(r, "75 comprimé(s) disponible(s)")

    def test_walk_in_sale_by_blister(self):
        StockMovement.objects.create(product=self.p, date=date(2026, 10, 1), kind=StockMovement.INITIAL,
                                     quantity=100)
        self.make_session(date(2026, 10, 15))
        self.client.force_login(self.cashier)
        self.client.post("/caisse/2026-10-15/vente-pharmacie/", {"patient_name": "", "phone": "", "sex": "", "age": "",
                                                                 "product": [self.p.id], "product_qty": [3],
                                                                 "product_unit": ["pack"]})
        sale = PharmacySale.objects.get()
        self.assertEqual((sale.unit_price, sale.amount, sale.units_per_item), (200, 600, 10))
        self.assertEqual(self.p.stock_qty, 70)

    def test_product_without_packaging_is_unchanged(self):
        plain = self.product("SIROP TOUX", initial=10, sale_price=1500, purchase_price=900)
        self.assertEqual((plain.purchase_size, plain.unit_cost, plain.has_pack, plain.describe(10)),
                         (1, 900, False, ""))


class ProductSupplierTests(StockBase):
    def test_choose_supplier_from_list(self):
        from .models import Supplier
        ubi = Supplier.objects.create(name="UBIPHARM")
        self.client.force_login(self.pharma)
        page = self.client.get("/stock/produit/nouveau/")
        self.assertContains(page, "UBIPHARM")
        self.assertContains(page, "+ Nouveau fournisseur")
        self.client.post("/stock/produit/nouveau/", {"name": "AMOXICILLINE 500", "form": "COMPRIME",
                                                     "unit": "plaquette", "sale_price": 1500, "pack_unit": "",
                                                     "supplier": ubi.id, "purchase_unit": "", "purchase_price": 1200,
                                                     "reorder_level": 5, "active": "on"})
        self.assertEqual(Product.objects.get(name="AMOXICILLINE 500").supplier, ubi)

    def test_quick_add_supplier_from_product_form(self):
        from .models import Supplier
        self.client.force_login(self.pharma)
        page = self.client.get("/stock/produit/nouveau/")
        self.assertContains(page, "+ Nouveau fournisseur")
        self.assertContains(page, "Conditionnement d&#x27;achat")
        r = self.client.post("/stock/fournisseur/ajouter/", {"name": "LABOREX", "phone": "0102030405", "address": ""})
        self.assertEqual(r.json(), {"id": Supplier.objects.get(name="LABOREX").id, "name": "LABOREX"})
        r = self.client.post("/stock/fournisseur/ajouter/", {"name": "LABOREX", "phone": "", "address": ""})
        self.assertEqual(r.status_code, 400)                    # nom déjà utilisé
        self.assertIn("name", r.json()["errors"])
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.post("/stock/fournisseur/ajouter/", {"name": "X"}).status_code, 403)


class ProductDeleteTests(StockBase):
    def test_delete_product_created_by_mistake(self):
        p = self.product("ERREUR DE SAISIE", initial=10)       # stock initial seulement
        self.client.force_login(self.pharma)
        self.assertContains(self.client.get(f"/stock/produit/{p.id}/"), "Supprimer le produit")
        r = self.client.post(f"/stock/produit/{p.id}/supprimer/")
        self.assertRedirects(r, "/stock/")
        self.assertFalse(Product.objects.filter(pk=p.pk).exists())

    def test_product_with_history_is_kept(self):
        p = self.product("VITAMINE C", initial=10, sale_price=25)
        PharmacySale.objects.create(session=self.make_session(date(2026, 10, 2)), product=p, quantity=1, unit_price=25)
        self.client.force_login(self.pharma)
        r = self.client.post(f"/stock/produit/{p.id}/supprimer/", follow=True)
        self.assertContains(r, "ne peut pas être supprimé")
        self.assertTrue(Product.objects.filter(pk=p.pk).exists())

    def test_only_pharmacy_can_delete(self):
        p = self.product("X")
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.post(f"/stock/produit/{p.id}/supprimer/").status_code, 403)
        self.assertTrue(Product.objects.filter(pk=p.pk).exists())


class PackagingConflictTests(StockBase):
    BASE = {"name": "AMOXICILLINE 500", "form": "COMPRIME", "unit": "plaquette", "sale_price": 500,
            "pack_unit": "boîte", "pack_size": 10, "pack_price": 5000, "purchase_price": 35000, "reorder_level": 20,
            "active": "on"}

    def test_same_word_two_sizes_is_refused(self):
        self.client.force_login(self.pharma)
        r = self.client.post("/stock/produit/nouveau/", {**self.BASE, "purchase_unit": "boîte", "purchase_size": 100})
        self.assertContains(r, "contient déjà 10 plaquette(s) à la vente")
        self.assertFalse(Product.objects.filter(name="AMOXICILLINE 500").exists())

    def test_distinct_words_or_same_size_are_accepted(self):
        self.client.force_login(self.pharma)
        self.client.post("/stock/produit/nouveau/", {**self.BASE, "purchase_unit": "carton", "purchase_size": 100})
        self.assertEqual(Product.objects.get(name="AMOXICILLINE 500").purchase_unit, "carton")
        self.client.post("/stock/produit/nouveau/", {**self.BASE, "name": "AMOX BIS", "purchase_unit": "boîte",
                                                     "purchase_size": 10})
        self.assertTrue(Product.objects.filter(name="AMOX BIS").exists())
