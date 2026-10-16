from datetime import date

from django.contrib.auth.models import Group, User

from core.models import AuditLog
from stock.models import Product, StockMovement

from .models import Act, ActPrice, CashSession, Visit
from .tests import Base

DAY = date(2026, 10, 15)
URL = "/caisse/2026-10-15"


class VisitBase(Base):
    def setUp(self):
        super().setUp()
        self.session = self.make_session(DAY)
        self.client.force_login(self.cashier)
        self.cpn = Act.objects.get(code="cpn")              # 1 000 F, caisse Entrées
        self.labo = Act.objects.create(code="goutte-epaisse", name="Goutte épaisse", category="LABO",
                                       is_lab=True)                # examen de laboratoire à prix fixe
        ActPrice.objects.create(act=self.labo, price=10000, valid_from=date(2026, 1, 1))
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

    def test_acts_table_is_read_only_and_counts_receipts(self):
        self.post_visit(acts=[(self.cpn, 1, "")])
        # quantités de la grille d'une journée importée d'Excel : toujours comptées
        self.session.entries.filter(act=self.cpn).update(quantity=3, amount=3000)
        page = self.client.get(f"{URL}/")
        self.assertNotContains(page, "En plus")
        self.assertNotContains(page, 'name="value"')
        row = next(e for g in page.context["groups"] for e in g["entries"] if e.act == self.cpn)
        self.assertEqual((row.total_qty, row.total_amount), (4, 4000))
        self.assertEqual(self.client.post(f"{URL}/acte/{row.id}/", {"value": "5"}).status_code, 404)

    def test_patients_are_paginated_newest_first(self):
        for i in range(25):
            self.post_visit(acts=[(self.cpn, 1, "")], patient_name=f"PATIENT {i:02d}")
        self.client.get(f"{URL}/")  # affiche (et vide) les messages « Reçu … enregistré »
        page = self.client.get(f"{URL}/")
        self.assertContains(page, "Patients 1–20 sur 25")
        self.assertContains(page, "PATIENT 24")
        self.assertNotContains(page, "PATIENT 04")
        self.assertEqual(page.context["by_cashier"][0]["count"], 25)   # résumé : toute la journée
        page2 = self.client.get(f"{URL}/?patients=2")
        self.assertContains(page2, "Patients 21–25 sur 25")
        self.assertContains(page2, "PATIENT 00")
        self.assertNotContains(page2, "PATIENT 24")

    def test_lab_amount_and_commissions(self):
        self.post_visit(acts=[(self.labo, 1, "")])
        t = self.totals()
        self.assertEqual((t.lab, t.commissions_paid, t.net_total), (10000, 7500, 2500))

    def test_invalid_visits_are_refused(self):
        self.assertContains(self.post_visit(), "Ajoutez au moins un acte ou un produit")
        self.post_visit(acts=[(self.cpn, 1, "")], patient_name=" ")
        act = Act.objects.create(code="sans-tarif", name="Sans tarif")
        self.assertContains(self.post_visit(acts=[(act, 1, "")]), "Aucun tarif")
        self.assertFalse(Visit.objects.exists())

    def test_stock_is_checked(self):
        r = self.post_visit(products=[(self.para, 11)])
        self.assertContains(r, "Stock insuffisant pour « PARACETAMOL 500 » : 10 unité(s) disponible(s)")
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


class PharmacySaleTests(VisitBase):
    """Client venu seulement pour des médicaments : reçu sans actes, nom facultatif."""

    def sell(self, qty, **client):
        data = {"patient_name": "", "phone": "", "sex": "", "age": "", "act": [self.cpn.id], "act_qty": [1],
                "act_amount": [""], "product": [self.para.id], "product_qty": [qty], "product_unit": ["unite"]}
        data.update(client)
        return self.client.post(f"{URL}/vente-pharmacie/", data, follow=True)

    def test_form_has_no_acts(self):
        page = self.client.get(f"{URL}/vente-pharmacie/")
        self.assertContains(page, "Vente de médicaments")
        self.assertNotContains(page, '<h2>Actes</h2>')
        self.assertContains(page, "Nom du client (facultatif)")
        self.assertContains(self.client.get(f"{URL}/"), f'href="{URL}/vente-pharmacie/"')

    def test_walk_in_sale_without_name_and_acts_ignored(self):
        r = self.sell(2)
        visit = Visit.objects.get()
        self.assertEqual((visit.kind, visit.patient_name, visit.total), (Visit.PHARMACY, "Client de passage", 100))
        self.assertFalse(visit.acts.exists())                     # un acte envoyé quand même est ignoré
        self.assertEqual(self.para.stock_qty, 8)
        self.assertContains(r, "+ Vente suivante")
        self.assertContains(self.client.get(f"{URL}/"), "Pharmacie</span>")
        edit = self.client.get(f"{URL}/patient/{visit.id}/modifier/")
        self.assertContains(edit, f"Modifier le reçu {visit.number}")
        self.assertNotContains(edit, "<h2>Actes</h2>")

    def test_stock_is_checked_and_a_product_is_required(self):
        self.assertContains(self.sell(12), "Stock insuffisant")
        r = self.client.post(f"{URL}/vente-pharmacie/", {"patient_name": "YAO", "product": [], "product_qty": []})
        self.assertContains(r, "Ajoutez au moins un produit.")
        self.assertFalse(Visit.objects.exists())


class NextStepsTests(VisitBase):
    def test_patient_counts_in_totals_and_report(self):
        self.post_visit(acts=[(self.cpn, 1, "")])
        self.post_visit(acts=[(self.cpn, 1, "")], patient_name="YAO Koffi")
        self.post_visit(acts=[(self.cpn, 1, "")], patient_name="Annulé")
        last = Visit.objects.get(patient_name="Annulé")
        self.client.post(f"{URL}/patient/{last.id}/annuler/", {"reason": "erreur"})
        self.assertEqual(self.totals().patients, 2)
        self.client.force_login(self.boss)
        r = self.client.get("/rapports/mensuel/", {"mois": "2026-10"})
        self.assertContains(r, "2 patient(s) enregistré(s)")
        self.assertEqual(self.client.get("/rapports/mensuel/excel/", {"mois": "2026-10"}).status_code, 200)
        self.assertEqual(self.client.get("/rapports/annuel/excel/", {"annee": "2026"}).status_code, 200)

    def test_takings_per_cashier(self):
        self.post_visit(acts=[(self.cpn, 2, "")])
        r = self.client.get(f"{URL}/")
        self.assertContains(r, "Reçus encaissés par caissier")
        self.assertEqual(r.context["by_cashier"], [{"name": "caissier", "count": 1, "amount": 2000}])

    def test_patient_search(self):
        self.post_visit(acts=[(self.cpn, 1, "")], phone="07 07 12 34 56", age="30")
        self.post_visit(acts=[(self.cpn, 1, "")], phone="0707123456", age="30")
        self.assertEqual(Visit.objects.first().phone, "0707123456")
        by_phone = self.client.get("/caisse/patients/recherche/", {"q": "0707 12"}).json()["patients"]
        self.assertEqual(len(by_phone), 1)
        self.assertEqual((by_phone[0]["name"], by_phone[0]["visits"], by_phone[0]["sex"]), ("KOUASSI Amenan", 2, "F"))
        self.assertEqual(len(self.client.get("/caisse/patients/recherche/", {"q": "koua"}).json()["patients"]), 1)
        self.assertEqual(self.client.get("/caisse/patients/recherche/", {"q": "zz"}).json()["patients"], [])
        pharma = User.objects.create_user("pharma2", password="x")
        pharma.groups.add(Group.objects.get(name="Pharmacie"))
        self.client.force_login(pharma)
        self.assertEqual(self.client.get("/caisse/patients/recherche/", {"q": "koua"}).status_code, 403)


class PharmacySaleRightsTests(VisitBase):
    def test_supervisor_cannot_sell_drugs(self):
        self.client.force_login(self.boss)
        self.assertNotContains(self.client.get(f"{URL}/"), "Vente de médicaments")
        self.assertEqual(self.client.get(f"{URL}/vente-pharmacie/").status_code, 403)
        # reçu de vente fait par la caisse : le superviseur peut l'annuler, pas le modifier
        self.client.force_login(self.cashier)
        self.client.post(f"{URL}/vente-pharmacie/", {"patient_name": "", "product": [self.para.id],
                                                     "product_qty": [1], "product_unit": ["unite"]})
        visit = Visit.objects.get()
        self.client.force_login(self.boss)
        receipt = self.client.get(f"{URL}/patient/{visit.id}/")
        self.assertNotContains(receipt, "Vente suivante")
        self.assertNotContains(receipt, f"{URL}/patient/{visit.id}/modifier/")
        self.assertContains(receipt, "Annuler ce reçu")
        self.assertEqual(self.client.get(f"{URL}/patient/{visit.id}/modifier/").status_code, 403)


class SupervisorReceiptRightsTests(VisitBase):
    def test_supervisor_cannot_create_patient_receipts_but_can_cancel(self):
        self.post_visit(acts=[(self.cpn, 1, "")])                # reçu fait par la caisse
        visit = Visit.objects.get()
        self.client.force_login(self.boss)
        page = self.client.get(f"{URL}/")
        self.assertNotContains(page, "+ Nouveau patient")
        self.assertNotContains(page, "lecture seule")            # il clôture et saisit les dépenses
        self.assertEqual(self.client.get(f"{URL}/patient/").status_code, 403)
        self.assertEqual(self.client.get(f"{URL}/patient/{visit.id}/modifier/").status_code, 403)
        self.assertNotContains(self.client.get(f"{URL}/patient/{visit.id}/"), "Patient suivant")
        self.client.post(f"{URL}/patient/{visit.id}/annuler/", {"reason": "doublon"})
        visit.refresh_from_db()
        self.assertTrue(visit.cancelled)

    def test_supervisor_can_open_a_day(self):
        self.client.force_login(self.boss)
        self.client.post("/caisse/ouvrir/", {"date": "2026-10-14"})
        self.assertTrue(CashSession.objects.filter(date=date(2026, 10, 14)).exists())
