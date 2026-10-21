from datetime import date
from io import StringIO

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
        call_command("init_fsu", "--demarrage", "2026-01-01", verbosity=0, stdout=StringIO())
        services.legacy_lab_act()  # montants de laboratoire des journées importées d'Excel
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
            e = (s.entries.filter(act__code=code).first()
                 or ActEntry.objects.create(session=s, act=Act.objects.get(code=code), quantity=0))
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
        Deposit.objects.create(facility=self.facility, date=day, account=BankAccount.objects.first(), amount=2000,
                               from_till=True)
        # seul le superviseur clôture la journée
        self.client.force_login(self.cashier)
        self.assertNotContains(self.client.get(f"/caisse/{day:%Y-%m-%d}/"), "Clôturer la journée")
        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/cloturer/", {"counted_cash": 2900, "notes": ""})
        self.assertEqual(r.status_code, 403)
        self.client.force_login(self.boss)
        self.assertContains(self.client.get(f"/caisse/{day:%Y-%m-%d}/"), "Clôturer la journée")
        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/cloturer/", {"counted_cash": 2900, "notes": ""})
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual(s.status, CashSession.CLOSED)
        self.assertEqual(s.expected_cash, 3000)   # 5 000 de CPN − 2 000 versés
        self.assertEqual(s.cash_gap, -100)

        # la caissière ne peut plus modifier, ni valider
        self.client.force_login(self.cashier)
        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/patient/", {"patient_name": "YAO Koffi"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/valider/", {"handed_over": 2900})
        self.assertEqual(r.status_code, 403)

        self.client.force_login(self.boss)
        self.client.post(f"/caisse/{day:%Y-%m-%d}/valider/")  # argent reçu obligatoire
        s.refresh_from_db()
        self.assertEqual(s.status, CashSession.CLOSED)
        self.client.post(f"/caisse/{day:%Y-%m-%d}/valider/", {"handed_over": 2900})
        s.refresh_from_db()
        self.assertEqual((s.status, s.handed_over, s.handover_gap), (CashSession.VALIDATED, 2900, 0))

        r = self.client.post(f"/caisse/{day:%Y-%m-%d}/rouvrir/", {"reason": ""})
        s.refresh_from_db()
        self.assertEqual(s.status, CashSession.VALIDATED)  # motif obligatoire
        self.client.post(f"/caisse/{day:%Y-%m-%d}/rouvrir/", {"reason": "erreur de saisie CPN"})
        s.refresh_from_db()
        self.assertEqual(s.status, CashSession.OPEN)
        self.assertTrue(AuditLog.objects.filter(action="reopen", details__motif="erreur de saisie CPN").exists())

    def test_cash_balance_carries_over(self):
        self.facility.opening_cash = 5000
        self.facility.save()
        self.make_session(date(2026, 1, 2), cpn=10)       # +10 000
        self.make_session(date(2026, 1, 3), cpn=4)        # +4 000
        Deposit.objects.create(facility=self.facility, date=date(2026, 1, 3), account=BankAccount.objects.first(),
                               amount=12000, from_till=True)
        services.clear_caches()
        self.assertEqual(services.cash_balance(date(2026, 1, 3), include_day=False), 15000)
        self.assertEqual(services.cash_balance(date(2026, 1, 3)), 7000)


class HandoverTests(Base):
    """Le superviseur clôture, reçoit l'argent du caissier en validant, puis le verse à la banque."""

    def close_and_validate(self, day, counted, received):
        self.client.force_login(self.boss)
        self.client.post(f"/caisse/{day:%Y-%m-%d}/cloturer/", {"counted_cash": counted, "notes": ""})
        return self.client.post(f"/caisse/{day:%Y-%m-%d}/valider/", {"handed_over": received}, follow=True)

    def test_money_moves_from_till_to_supervisor_to_bank(self):
        day = date(2026, 10, 5)
        self.make_session(day, cpn=5)                                     # 5 000 F
        services.clear_caches()
        self.assertEqual((services.cash_balance(day), services.supervisor_balance(day)), (5000, 0))
        self.close_and_validate(day, 5000, 5000)
        self.assertEqual((services.cash_balance(day), services.supervisor_balance(day)), (0, 5000))
        self.client.post("/versements/ajouter/", {"date": "2026-10-06", "account": BankAccount.objects.first().id,
                                                  "amount": 5000, "reference": "", "depositor": "", "note": ""})
        d = Deposit.objects.get()
        self.assertFalse(d.from_till)
        nxt = date(2026, 10, 6)
        self.assertEqual((services.cash_balance(nxt), services.supervisor_balance(nxt)), (0, 0))
        # la journée suivante commence avec une caisse vide
        self.make_session(nxt, cpn=1)
        self.client.post(f"/caisse/{nxt:%Y-%m-%d}/cloturer/", {"counted_cash": 1000, "notes": ""})
        self.assertEqual(CashSession.objects.get(date=nxt).cash_gap, 0)

    def test_short_handover_is_flagged_and_stays_in_till(self):
        day = date(2026, 10, 5)
        self.make_session(day, cpn=5)
        r = self.close_and_validate(day, 5000, 4500)
        self.assertContains(r, "diffère de -500 F")
        s = CashSession.objects.get(date=day)
        self.assertEqual(s.handover_gap, -500)
        self.assertEqual(AuditLog.objects.filter(action="validate").last().details["écart de remise"], -500)
        services.clear_caches()
        self.assertEqual((services.cash_balance(day), services.supervisor_balance(day)), (500, 4500))

    def test_reopen_keeps_handover_and_revalidation_corrects_it(self):
        day = date(2026, 10, 5)
        self.make_session(day, cpn=5)
        self.close_and_validate(day, 5000, 5000)
        self.client.post(f"/caisse/{day:%Y-%m-%d}/rouvrir/", {"reason": "CPN oubliée"})
        self.assertEqual(CashSession.objects.get(date=day).handed_over, 5000)
        self.client.post(f"/caisse/{day:%Y-%m-%d}/cloturer/", {"counted_cash": 6000, "notes": ""})
        self.assertContains(self.client.get(f"/caisse/{day:%Y-%m-%d}/"), 'value="6000"')  # pré-rempli : argent compté
        self.client.post(f"/caisse/{day:%Y-%m-%d}/valider/", {"handed_over": 6000})
        self.assertEqual(CashSession.objects.get(date=day).handed_over, 6000)

    def test_only_supervisor_records_bank_deposits(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get("/versements/").status_code, 403)
        r = self.client.post("/versements/ajouter/", {"date": "2026-10-06", "account": BankAccount.objects.first().id,
                                                      "amount": 100})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Deposit.objects.exists())
        self.assertNotContains(self.client.get("/"), 'href="/versements/"')
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get("/versements/").status_code, 200)
        self.assertContains(self.client.get("/"), "Chez le superviseur")


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


class ExpenseAccessTests(Base):
    """Les dépenses payées en espèces sont réservées au superviseur (et aux administrateurs)."""

    def test_only_supervisor_sees_and_records_expenses(self):
        day = date(2026, 10, 5)
        self.make_session(day)
        data = {"category": ExpenseCategory.objects.first().id, "fund": FUND_ENTREE, "amount": 1500,
                "description": "Rame de papier", "beneficiary": ""}
        self.client.force_login(self.cashier)
        self.assertNotContains(self.client.get(f"/caisse/{day:%Y-%m-%d}/"), "Dépenses payées en espèces")
        self.assertEqual(self.client.post(f"/caisse/{day:%Y-%m-%d}/depense/", data).status_code, 403)
        self.assertFalse(Expense.objects.exists())
        self.client.force_login(self.boss)
        self.assertContains(self.client.get(f"/caisse/{day:%Y-%m-%d}/"), "Ajouter la dépense")
        self.client.post(f"/caisse/{day:%Y-%m-%d}/depense/", data)
        expense = Expense.objects.get()
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.post(f"/caisse/{day:%Y-%m-%d}/depense/{expense.id}/supprimer/").status_code, 403)
        self.assertTrue(Expense.objects.exists())


class MonthlyDetailTests(Base):
    def test_detail_lists_each_day_with_its_acts_only(self):
        self.make_session(date(2026, 10, 15), cpn=2)
        self.make_session(date(2026, 10, 16), **{"consultation-curative": 1})
        self.client.force_login(self.boss)
        r = self.client.get("/rapports/mensuel/?mois=2026-10&vue=detail")
        days = [d for d in r.context["day_details"] if d["session"]]
        self.assertEqual([[(l["act"].code, l["qty"], l["price"], l["amount"]) for l in d["lines"]] for d in days],
                         [[("cpn", 2, 1000, 2000)], [("consultation-curative", 1, 1000, 1000)]])
        self.assertContains(r, '<details class="day-row">', count=2)
        self.assertContains(r, "2 × 1")

    def test_every_day_of_the_month_is_listed_missing_ones_flagged(self):
        self.make_session(date(2026, 9, 2), cpn=1)
        self.client.force_login(self.boss)
        r = self.client.get("/rapports/mensuel/?mois=2026-09&vue=detail")
        self.assertEqual((r.context["days_listed"], r.context["days_entered"]), (30, 1))
        self.assertContains(r, "1 journée saisie sur 30")
        self.assertContains(r, "Journée non saisie", count=29)


class AnnualYearPickerTests(Base):
    def test_year_dropdown_lists_years_with_current_selected(self):
        self.client.force_login(self.boss)
        r = self.client.get("/rapports/annuel/?annee=2026")
        self.assertContains(r, '<select name="annee"')
        self.assertContains(r, '<option value="2026" selected>2026</option>', html=True)
        self.assertNotContains(r, "2027 →")
        self.assertEqual(r.context["years"][0], max(r.context["years"]))

    def test_no_future_year(self):
        from django.utils import timezone
        this_year = timezone.localdate().year
        self.client.force_login(self.boss)
        r = self.client.get(f"/rapports/annuel/?annee={this_year + 1}")
        self.assertEqual(r.context["year"], this_year)
        self.assertEqual(r.context["years"][0], this_year)
        self.assertNotContains(r, f'<option value="{this_year + 1}"')

    def test_previous_years_always_offered(self):
        from django.utils import timezone
        this_year = timezone.localdate().year
        self.client.force_login(self.boss)
        r = self.client.get("/rapports/annuel/")
        self.assertEqual(r.context["years"][:6], list(range(this_year, this_year - 6, -1)))
        self.assertContains(r, f'<option value="{this_year - 1}">{this_year - 1}</option>', html=True)


class NoFutureDaysTests(Base):
    def test_day_and_month_navigation_stop_at_today(self):
        from datetime import timedelta
        from django.utils import timezone
        today = timezone.localdate()
        self.make_session(today)
        self.client.force_login(self.cashier)
        page = self.client.get(f"/caisse/{today:%Y-%m-%d}/")
        self.assertIsNone(page.context["today_day"])          # déjà aujourd'hui : pas de bouton
        self.assertNotContains(page, "Aujourd'hui (")
        tomorrow = today + timedelta(days=1)
        self.assertRedirects(self.client.get(f"/caisse/{tomorrow:%Y-%m-%d}/"), f"/caisse/{today:%Y-%m-%d}/")
        yesterday = today - timedelta(days=1)                   # journée pas ouverte : navigation aussi
        missing = self.client.get(f"/caisse/{yesterday:%Y-%m-%d}/")
        self.assertContains(missing, f"Aujourd'hui ({today:%d/%m})")
        self.assertContains(missing, "Jour précédent")
        self.assertNotContains(missing, "Jour suivant")
        months = self.client.get("/caisse/")
        self.assertIsNone(months.context["next_month"])
        far = self.client.get(f"/caisse/?mois={today.year + 1}-01")
        self.assertEqual(far.context["start"], today.replace(day=1))

    def test_today_page_when_not_opened(self):
        self.client.force_login(self.cashier)
        r = self.client.get("/caisse/aujourdhui/")
        self.assertContains(r, "pas encore été ouverte")
        self.assertNotContains(r, "Aujourd'hui (")
