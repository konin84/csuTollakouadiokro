from datetime import date

from django.contrib.auth.models import Group, User

from core.models import AuditLog
from stock.models import Product, StockMovement

from .models import Act, CashSession, Visit
from .tests import Base

DAY = date(2026, 10, 15)
URL = "/caisse/2026-10-15"


class VisitBase(Base):
    def setUp(self):
        super().setUp()
        self.session = self.make_session(DAY)
        self.client.force_login(self.cashier)
        self.cpn = Act.objects.get(code="cpn")              # 1 000 F, caisse Entrées
        self.labo = Act.objects.get(code="laboratoire")     # montant saisi
        self.para = Product.objects.create(name="PARACETAMOL 500", sale_price=50, purchase_price=20)
        StockMovement.objects.create(product=self.para, date=date(2026, 10, 1), kind=StockMovement.INITIAL,
                                     quantity=10)

    def post_visit(self, acts=(), products=(), url=None, **patient):
        data = {"patient_name": "KOUASSI Amenan", "phone": "", "sex": "F", "age": "27",
                "act": [], "act_qty": [], "act_amount": [], "product": [], "product_qty": []}
        data.update(patient)
        for act, qty, amount in acts:
            data["act"].append(act.id)
            data["act_qty"].append(qty)
            data["act_amount"].append(amount)
        for product, qty in products:
            data["product"].append(product.id)
            data["product_qty"].append(qty)
        return self.client.post(url or f"{URL}/patient/", data)

    def totals(self, s=None):
        return super().totals(s or self.session)


class VisitTests(VisitBase):
    def test_visit_with_acts_and_products(self):
        r = self.post_visit(acts=[(self.cpn, 2, "")], products=[(self.para, 4)])
        visit = Visit.objects.get()
        self.assertRedirects(r, f"{URL}/patient/{visit.id}/")
        self.assertEqual((visit.number, visit.patient_name, visit.age, visit.created_by),
                         ("2026-000001", "KOUASSI Amenan", 27, self.cashier))
        line = visit.acts.get()
        self.assertEqual((line.quantity, line.unit_price, line.amount), (2, 1000, 2000))  # prix du tarif
        self.assertEqual(visit.total, 2200)
        self.assertEqual(self.para.stock_qty, 6)
        t = self.totals()
        self.assertEqual((t.acts_qty[self.cpn.id], t.pharmacy, t.net_total), (2, 200, 2200))
        receipt = self.client.get(f"{URL}/patient/{visit.id}/")
        self.assertContains(receipt, "2026-000001")
        self.assertContains(receipt, "KOUASSI Amenan")

    def test_numbers_follow_each_other(self):
        self.post_visit(acts=[(self.cpn, 1, "")])
        self.post_visit(acts=[(self.cpn, 1, "")], patient_name="YAO Koffi")
        self.assertEqual(list(Visit.objects.values_list("number", flat=True)), ["2026-000001", "2026-000002"])

    def test_grid_counts_add_to_visits(self):
        self.post_visit(acts=[(self.cpn, 1, "")])
        entry = self.session.entries.get(act=self.cpn)
        r = self.client.post(f"{URL}/acte/{entry.id}/", {"value": "3"}, HTTP_HX_REQUEST="true")
        self.assertContains(r, "4 000")  # montant total de la ligne : 1 patient + 3 en plus
        self.assertEqual(self.totals().acts_qty[self.cpn.id], 4)
        page = self.client.get(f"{URL}/")
        self.assertContains(page, "Patients du jour")

    def test_lab_amount_and_commissions(self):
        self.post_visit(acts=[(self.labo, 1, 10000)])
        t = self.totals()
        self.assertEqual((t.lab, t.commissions_paid, t.net_total), (10000, 7500, 2500))

    def test_invalid_visits_are_refused(self):
        self.assertContains(self.post_visit(), "Ajoutez au moins un acte ou un produit")
        self.assertContains(self.post_visit(acts=[(self.labo, 1, "")]), "Indiquez le montant")
        self.post_visit(acts=[(self.cpn, 1, "")], patient_name=" ")
        act = Act.objects.create(code="sans-tarif", name="Sans tarif")
        self.assertContains(self.post_visit(acts=[(act, 1, "")]), "Aucun tarif")
        self.assertFalse(Visit.objects.exists())

    def test_stock_is_checked(self):
        r = self.post_visit(products=[(self.para, 11)])
        self.assertContains(r, "Stock insuffisant pour « PARACETAMOL 500 » : 10 disponible(s)")
        self.assertFalse(Visit.objects.exists())
        self.facility.block_negative_stock = False
        self.facility.save()
        self.post_visit(products=[(self.para, 11)])
        self.assertEqual(self.para.stock_qty, -1)

    def test_edit_visit_adjusts_stock(self):
        self.post_visit(acts=[(self.cpn, 1, "")], products=[(self.para, 10)])  # tout le stock
        visit = Visit.objects.get()
        # la quantité déjà sur le reçu compte comme disponible
        r = self.post_visit(products=[(self.para, 8)], url=f"{URL}/patient/{visit.id}/modifier/",
                            patient_name="KOUASSI Amenan Marie")
        self.assertRedirects(r, f"{URL}/patient/{visit.id}/")
        visit.refresh_from_db()
        self.assertEqual((visit.patient_name, visit.number, visit.acts.count()), ("KOUASSI Amenan Marie",
                                                                                   "2026-000001", 0))
        self.assertEqual(self.para.stock_qty, 2)

    def test_cancel_visit(self):
        self.post_visit(acts=[(self.cpn, 1, "")], products=[(self.para, 3)])
        visit = Visit.objects.get()
        self.client.post(f"{URL}/patient/{visit.id}/annuler/", {"reason": ""})
        visit.refresh_from_db()
        self.assertFalse(visit.cancelled)  # motif obligatoire
        self.client.post(f"{URL}/patient/{visit.id}/annuler/", {"reason": "erreur de patient"})
        visit.refresh_from_db()
        self.assertTrue(visit.cancelled)
        self.assertEqual(self.para.stock_qty, 10)
        self.assertEqual(self.totals().net_total, 0)
        self.assertTrue(AuditLog.objects.filter(action="cancel", details__motif="erreur de patient").exists())
        self.assertContains(self.client.get(f"{URL}/"), "Annulé")
        self.assertEqual(self.client.get(f"{URL}/patient/{visit.id}/modifier/").status_code, 403)

    def test_visit_sale_not_deletable_from_day_sales(self):
        self.post_visit(products=[(self.para, 1)])
        sale = Visit.objects.get().sales.get()
        r = self.client.post(f"{URL}/vente/{sale.id}/supprimer/")
        self.assertEqual(r.status_code, 404)


class ConsumptionTests(VisitBase):
    def test_act_consumes_product(self):
        gants = Product.objects.create(name="GANTS (paire)", purchase_price=50)
        StockMovement.objects.create(product=gants, date=date(2026, 10, 1), kind=StockMovement.INITIAL,
                                     quantity=100)
        gant = Act.objects.get(code="gant")
        gant.product, gant.product_quantity = gants, 2
        gant.save()
        self.post_visit(acts=[(gant, 3, "")])
        self.assertEqual(gants.stock_qty, 94)
        entry = self.session.entries.get(act=gant)
        self.client.post(f"{URL}/acte/{entry.id}/", {"value": "5"})  # 5 de plus dans la grille
        self.assertEqual(gants.stock_qty, 84)
        movement = gants.movements.get(kind=StockMovement.CONSUMPTION)
        self.assertEqual((movement.quantity, movement.date), (-16, DAY))
        self.client.post(f"{URL}/patient/{Visit.objects.get().id}/annuler/", {"reason": "doublon"})
        self.assertEqual(gants.stock_qty, 90)


class AccessTests(VisitBase):
    def test_closed_day_and_roles(self):
        pharma = User.objects.create_user("pharma", password="x")
        pharma.groups.add(Group.objects.get(name="Pharmacie"))
        self.client.force_login(pharma)
        self.assertEqual(self.client.get(f"{URL}/patient/").status_code, 403)
        self.client.force_login(self.cashier)
        self.post_visit(acts=[(self.cpn, 1, "")])
        visit = Visit.objects.get()
        CashSession.objects.filter(pk=self.session.pk).update(status=CashSession.CLOSED)
        self.assertEqual(self.client.get(f"{URL}/patient/").status_code, 403)
        self.assertEqual(self.client.get(f"{URL}/patient/{visit.id}/modifier/").status_code, 403)
        r = self.client.get(f"{URL}/patient/{visit.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Annuler ce reçu")


class DaySaleStockTests(VisitBase):
    def test_day_sale_form_checks_stock(self):
        self.client.post(f"{URL}/vente/", {"product": self.para.id, "quantity": 12, "unit_price": 50,
                                           "description": ""}, HTTP_HX_REQUEST="true")
        self.assertEqual(self.para.stock_qty, 10)
        self.client.post(f"{URL}/vente/", {"product": self.para.id, "quantity": 2, "unit_price": 50,
                                           "description": ""}, HTTP_HX_REQUEST="true")
        self.assertEqual(self.para.stock_qty, 8)
