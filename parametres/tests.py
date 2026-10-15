from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.utils import timezone

from caisse import services
from caisse.models import Act, ActPrice, BankAccount, CommissionRule, ExpenseCategory
from caisse.tests import Base
from core.models import AuditLog, Facility
from stock.models import Supplier


class SettingsBase(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_superuser("chef", password="x")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)


class AccessTests(SettingsBase):
    PAGES = ["/parametres/", "/parametres/etablissement/", "/parametres/utilisateurs/",
             "/parametres/utilisateurs/nouveau/", "/parametres/actes/", "/parametres/actes/nouveau/",
             "/parametres/commissions/", "/parametres/categories/", "/parametres/banques/",
             "/parametres/banques/nouveau/"]

    def test_admin_sees_every_page(self):
        act = Act.objects.get(code="cpn")
        rule = CommissionRule.objects.first()
        details = ["/parametres/fournisseurs/", f"/parametres/actes/{act.id}/",
                   f"/parametres/utilisateurs/{self.cashier.id}/", f"/parametres/commissions/{rule.id}/"]
        for url in self.PAGES + details:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(f"/parametres/actes/{act.id}/"), "Nouveau tarif")
        self.assertContains(self.client.get(f"/parametres/utilisateurs/{self.cashier.id}/"),
                            "Changer le mot de passe")

    def test_supervisor_is_refused(self):
        self.client.force_login(self.boss)
        for url in self.PAGES:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_pharmacy_manages_suppliers_only(self):
        pharma = User.objects.create_user("pharma", password="x")
        pharma.groups.add(Group.objects.get(name="Pharmacie"))
        self.client.force_login(pharma)
        self.client.post("/parametres/fournisseurs/nouveau/", {"name": "UBIPHARM", "phone": "", "address": ""})
        self.assertTrue(Supplier.objects.filter(name="UBIPHARM").exists())
        self.assertEqual(self.client.get("/parametres/banques/").status_code, 403)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get("/parametres/fournisseurs/").status_code, 403)

    def test_unknown_list_is_404(self):
        self.assertEqual(self.client.get("/parametres/inconnu/").status_code, 404)

    def test_menu_links_to_settings_not_django_admin(self):
        r = self.client.get("/")
        self.assertContains(r, 'href="/parametres/"')
        self.assertNotContains(r, 'href="/admin/"')


class FacilityTests(SettingsBase):
    def test_edit_facility_is_logged(self):
        r = self.client.post("/parametres/etablissement/", {
            "name": "FSU COM KOTTIAKOFFIKRO", "short_name": "FSU KK", "address": "", "phone": "",
            "opening_date": "2026-01-01", "opening_cash": 25000, "cash_tolerance": 500})
        self.assertRedirects(r, "/parametres/")
        self.assertEqual(Facility.current().opening_cash, 25000)
        self.assertTrue(AuditLog.objects.filter(model="établissement", action="update").exists())


class UserTests(SettingsBase):
    def new_user(self, **extra):
        data = {"username": "awa", "first_name": "Awa", "last_name": "Koné", "is_active": "on",
                "roles": ["Caissier"], "password1": "caisse-2026", "password2": "caisse-2026"}
        data.update(extra)
        return self.client.post("/parametres/utilisateurs/nouveau/", data)

    def test_create_user_with_roles(self):
        self.assertRedirects(self.new_user(roles=["Caissier", "Pharmacie"]), "/parametres/utilisateurs/")
        user = User.objects.get(username="awa")
        self.assertEqual(set(user.groups.values_list("name", flat=True)), {"Caissier", "Pharmacie"})
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertTrue(self.client.login(username="awa", password="caisse-2026"))
        entry = AuditLog.objects.get(model="utilisateur", action="create")
        self.assertNotIn("caisse-2026", str(entry.details))

    def test_password_rules(self):
        self.new_user(password2="autre-chose")
        self.new_user(password1="abc", password2="abc")  # trop court
        self.assertFalse(User.objects.filter(username="awa").exists())

    def test_change_roles_and_deactivate(self):
        self.new_user()
        user = User.objects.get(username="awa")
        self.client.post(f"/parametres/utilisateurs/{user.id}/", {
            "username": "awa", "first_name": "Awa", "last_name": "Koné", "roles": ["Superviseur"]})
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Superviseur"])
        log = AuditLog.objects.get(model="utilisateur", action="update")
        self.assertEqual(log.details["modifications"]["rôles"], ["Caissier", "Superviseur"])
        self.assertFalse(self.client.login(username="awa", password="caisse-2026"))

    def test_admin_cannot_lock_themself_out(self):
        self.client.post(f"/parametres/utilisateurs/{self.admin.id}/", {"username": "chef", "roles": []})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active and self.admin.is_superuser)

    def test_last_admin_cannot_be_removed(self):
        other = User.objects.create_superuser("chef2", password="x")
        self.client.force_login(other)
        self.client.post(f"/parametres/utilisateurs/{self.admin.id}/", {"username": "chef", "is_active": "on"})
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_superuser)  # chef2 reste administrateur : autorisé
        self.client.force_login(self.admin)
        other.is_superuser = True
        self.admin.is_superuser = True
        self.admin.save()
        other.is_active = False
        other.save()
        self.client.post(f"/parametres/utilisateurs/{self.admin.id}/", {"username": "chef", "is_active": "on"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)

    def test_reset_password(self):
        r = self.client.post(f"/parametres/utilisateurs/{self.cashier.id}/mot-de-passe/",
                             {"new_password1": "nouveau-2026", "new_password2": "nouveau-2026"})
        self.assertRedirects(r, "/parametres/utilisateurs/")
        self.assertTrue(self.client.login(username="caissier", password="nouveau-2026"))


class ActTests(SettingsBase):
    def test_create_act_with_price(self):
        r = self.client.post("/parametres/actes/nouveau/", {
            "name": "Vaccination", "category": "SOINS", "fund": "ENTREE", "entry_mode": "QTE", "order": 300,
            "active": "on", "price": 500, "valid_from": "2026-01-01"})
        act = Act.objects.get(name="Vaccination")
        self.assertRedirects(r, f"/parametres/actes/{act.id}/")
        self.assertEqual(act.code, "vaccination")
        self.assertEqual(act.price_on(date(2026, 6, 1)), 500)

    def test_quantity_act_requires_a_price(self):
        self.client.post("/parametres/actes/nouveau/", {
            "name": "Sans prix", "category": "SOINS", "fund": "ENTREE", "entry_mode": "QTE", "order": 1})
        self.assertFalse(Act.objects.filter(name="Sans prix").exists())

    def test_new_price_keeps_history(self):
        act = Act.objects.get(code="cpn")
        later = timezone.localdate() + timedelta(days=30)
        self.client.post(f"/parametres/actes/{act.id}/tarif/", {"price": 1500, "valid_from": later.isoformat()})
        self.assertEqual(act.price_on(later), 1500)
        self.assertEqual(act.price_on(date(2026, 2, 1)), 1000)
        r = self.client.post(f"/parametres/actes/{act.id}/tarif/", {"price": 9, "valid_from": later.isoformat()})
        self.assertContains(r, "Un tarif existe déjà à cette date")

    def test_only_future_prices_can_be_deleted(self):
        act = Act.objects.get(code="cpn")
        past = act.prices.get()
        future = ActPrice.objects.create(act=act, price=2000, valid_from=timezone.localdate() + timedelta(days=5))
        self.client.post(f"/parametres/actes/{act.id}/tarif/{past.id}/supprimer/")
        self.client.post(f"/parametres/actes/{act.id}/tarif/{future.id}/supprimer/")
        self.assertEqual(list(act.prices.all()), [past])

    def test_entry_mode_locked_once_used(self):
        self.make_session(date(2026, 3, 2), cpn=1)
        act = Act.objects.get(code="cpn")
        self.client.post(f"/parametres/actes/{act.id}/", {
            "name": "CPN", "category": "MATERNITE", "fund": "ENTREE", "entry_mode": "MONTANT", "order": 30,
            "active": "on"})
        act.refresh_from_db()
        self.assertEqual((act.name, act.entry_mode), ("CPN", "QTE"))


class SimpleListTests(SettingsBase):
    def test_commission_change_applies_without_restart(self):
        s = self.make_session(date(2026, 10, 1), laboratoire=10000)
        self.assertEqual(self.totals(s).commissions_paid, 7500)
        rule = CommissionRule.objects.get(beneficiary="Prescripteurs")
        self.client.post(f"/parametres/commissions/{rule.id}/", {
            "name": rule.name, "beneficiary": rule.beneficiary, "rate": 10, "valid_from": "2026-01-01",
            "valid_to": "", "order": rule.order})
        self.assertEqual(self.totals(s).commissions_paid, 7000)  # cache vidé automatiquement

    def test_commission_total_warning(self):
        self.assertNotContains(self.client.get("/parametres/commissions/"), "au lieu de 100")
        CommissionRule.objects.filter(beneficiary="ONG AIP").update(rate=20)
        self.assertContains(self.client.get("/parametres/commissions/"), "totalisent 95 %")

    def test_commission_end_before_start_refused(self):
        rule = CommissionRule.objects.get(beneficiary="ONG AIP")
        self.client.post(f"/parametres/commissions/{rule.id}/", {
            "name": rule.name, "beneficiary": rule.beneficiary, "rate": 25, "retained": "on",
            "valid_from": "2026-01-01", "valid_to": "2025-12-31", "order": rule.order})
        rule.refresh_from_db()
        self.assertIsNone(rule.valid_to)

    def test_add_category_and_bank(self):
        self.client.post("/parametres/categories/nouveau/", {"name": "Électricité", "default_fund": "ENTREE",
                                                             "order": 110, "active": "on"})
        self.client.post("/parametres/banques/nouveau/", {"bank": "AFG Bank", "name": "AFG Bank", "number": "",
                                                          "fund": "PHARMA", "active": "on"})
        self.assertTrue(ExpenseCategory.objects.filter(name="Électricité").exists())
        self.assertTrue(BankAccount.objects.filter(bank="AFG Bank", fund="PHARMA").exists())
