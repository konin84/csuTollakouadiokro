from datetime import date

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase

from caisse import services
from caisse.models import (FUND_ENTREE, FUND_PHARMA, Act, ActEntry, ActPrice, BankAccount, CashSession, Deposit,
                           Expense, ExpenseCategory, PharmacySale)
from core.models import AuditLog, Facility
from stock.models import Product, StockMovement


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_fsu", "--demarrage", "2026-01-01", verbosity=0)
        cls.facility = Facility.current()
        cls.cashier = User.objects.create_user("caissier", password="x")
        cls.cashier.groups.add(Group.objects.get(name="Caissier"))
        cls.boss = User.objects.create_user("major", password="x")
        cls.boss.groups.add(Group.objects.get(name="Superviseur"))

    def setUp(self):
        services.clear_caches()

    def make_session(self, day, **amounts):
        s = CashSession.objects.create(facility=self.facility, date=day)
        services.ensure_entries(s)
        for code, value in amounts.items():
            e = s.entries.get(act__code=code)
            if e.act.by_quantity:
                e.quantity = value
            else:
                e.amount = value
                e.manual_amount = True
            e.save()
        return s

    def totals(self, s):
        return services.session_totals(services.sessions_queryset().get(pk=s.pk))


class ExcelFormulaTests(Base):
    """Reproduit la ligne du 1er octobre 2026 de l'ancien tableau Excel."""

    def test_october_first_row(self):
        s = self.make_session(
            date(2026, 10, 1),
            **{"consultation-curative": 10, "consultation-eleves": 1, "cpn": 6, "mise-pose": 3,
               "carnet-mere-enfant": 1, "carnet-individuel": 11, "pansement": 2, "controle-ta": 3, "gant": 6,
               "bandelette-urinaire": 6, "laboratoire": 40000},
        )
        PharmacySale.objects.create(session=s, description="Ventes", quantity=1, unit_price=33175)
        Expense.objects.create(session=s, category=ExpenseCategory.objects.get(name__startswith="Consommables"),
                               fund=FUND_ENTREE, amount=51000, description="achat solutés")
        t = self.totals(s)
        self.assertEqual(t.acts_total, 69200)          # colonne U
        self.assertEqual(t.commissions_paid, 30000)    # 15 % + 60 % de 40 000
        self.assertEqual(t.commissions_retained, 10000)  # 25 % ONG AIP
        self.assertEqual(t.net_entree, -11800)         # colonne AI
        self.assertEqual(t.net_pharma, 33175)          # colonne AH
        self.assertEqual(t.net_total, 21375)           # colonne AJ

    def test_echography_counts_as_revenue(self):
        s = self.make_session(date(2026, 8, 1), echographie=10)
        cat = ExpenseCategory.objects.get(name__startswith="Ristourne médecin")
        Expense.objects.create(session=s, category=cat, fund=FUND_PHARMA, amount=30000, description="ristourne")
        t = self.totals(s)
        self.assertEqual(t.echo, 100000)
        self.assertEqual(t.net_pharma, 70000)
        self.assertEqual(t.net_total, 70000)


class PriceTests(Base):
    def test_price_change_applies_from_its_date(self):
        act = Act.objects.get(code="echographie")
        ActPrice.objects.create(act=act, price=12000, valid_from=date(2026, 11, 1))
        before = self.make_session(date(2026, 10, 31), echographie=2)
        after = self.make_session(date(2026, 11, 2), echographie=2)
        self.assertEqual(self.totals(before).echo, 20000)
        self.assertEqual(self.totals(after).echo, 24000)
        # le prix enregistré sur la journée ne change pas après coup
        ActPrice.objects.filter(act=act, valid_from=date(2026, 1, 1)).update(price=15000)
        before.entries.get(act=act).save()
        self.assertEqual(self.totals(before).echo, 20000)


class WorkflowTests(Base):
    def test_close_validate_reopen(self):
        day = date(2026, 10, 5)
        s = self.make_session(day, cpn=5)
        Deposit.objects.create(facility=self.facility, date=day, account=BankAccount.objects.first(), amount=2000)
        self.client.force_login(self.cashier)
        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/cloturer/", {"counted_cash": 2900, "notes": ""})
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.status, CashSession.CLOSED)
        self.assertEqual(s.expected_cash, 3000)   # 5 000 de CPN − 2 000 versés
        self.assertEqual(s.cash_gap, -100)

        # la caissière ne peut plus modifier, ni valider
        entry = s.entries.get(act__code="cpn")
        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/acte/{entry.id}/", {"value": 9})
        self.assertEqual(r.status_code, 403)
        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/valider/")
        self.assertEqual(r.status_code, 403)

        self.client.force_login(self.boss)
        self.client.post(f"/caisse/{day:%Y-%m-%d}/valider/")
        s.refresh_from_db()
        self.assertEqual(s.status, CashSession.VALIDATED)

        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/rouvrir/", {"reason": ""})
        s.refresh_from_db()
        self.assertEqual(s.status, CashSession.VALIDATED)  # motif obligatoire
        self.client.post(f"/caisse/{day:%Y-%m-%d}/rouvrir/", {"reason": "erreur de saisie CPN"})
        s.refresh_from_db()
        self.assertEqual(s.status, CashSession.OPEN)
        self.assertTrue(AuditLog.objects.filter(action="reopen", details__motif="erreur de saisie CPN").exists())

    def test_entry_update_via_htmx(self):
        day = date(2026, 10, 6)
        s = self.make_session(day)
        entry = s.entries.get(act__code="consultation-curative")
        self.client.force_login(self.cashier)
        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/acte/{entry.id}/", {"value": "12"}, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual((entry.quantity, entry.amount), (12, 12000))
        self.assertContains(r, "12 000")

    def test_cash_balance_carries_over(self):
        self.facility.opening_cash = 5000
        self.facility.save()
        self.make_session(date(2026, 1, 2), cpn=10)       # +10 000
        self.make_session(date(2026, 1, 3), cpn=4)        # +4 000
        Deposit.objects.create(facility=self.facility, date=date(2026, 1, 3), account=BankAccount.objects.first(),
                               amount=12000)
        services.clear_caches()
        self.assertEqual(services.cash_balance(date(2026, 1, 3), include_day=False), 15000)
        self.assertEqual(services.cash_balance(date(2026, 1, 3)), 7000)


class StockTests(Base):
    def test_sale_moves_stock(self):
        p = Product.objects.create(name="PARACETAMOL 500", sale_price=50, purchase_price=20)
        StockMovement.objects.create(product=p, date=date(2026, 10, 1), kind=StockMovement.INITIAL, quantity=100)
        s = self.make_session(date(2026, 10, 2))
        sale = PharmacySale.objects.create(session=s, product=p, quantity=8, unit_price=50)
        self.assertEqual(p.stock_qty, 92)
        self.assertEqual(self.totals(s).pharmacy, 400)
        sale.quantity = 10
        sale.save()
        self.assertEqual(p.stock_qty, 90)
        sale.delete()
        self.assertEqual(p.stock_qty, 100)

    def test_receive_order(self):
        pharma = User.objects.create_user("pharma", password="x")
        pharma.groups.add(Group.objects.get(name="Pharmacie"))
        p = Product.objects.create(name="FER SIROP", purchase_price=900)
        self.client.force_login(pharma)
        self.client.post("/stock/commandes/nouvelle/", {"date": "2026-10-10", "note": ""})
        from stock.models import PurchaseOrder

        order = PurchaseOrder.objects.get()
        self.assertEqual(order.number, "BC-2026-001")
        self.client.post(f"/stock/commandes/{order.id}/", {"product": p.id, "quantity": 100, "unit_cost": 950})
        self.client.post(f"/stock/commandes/{order.id}/statut/", {"action": "commander"})
        line = order.lines.get()
        self.client.post(f"/stock/commandes/{order.id}/reception/", {"date": "2026-10-12", f"qty_{line.id}": 96})
        p.refresh_from_db()
        self.assertEqual(p.stock_qty, 96)
        self.assertEqual(p.purchase_price, 950)
