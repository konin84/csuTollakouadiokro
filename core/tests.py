from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase


class SupervisorAccountTests(TestCase):
    def init(self, *args):
        out = StringIO()
        call_command("init_fsu", *args, verbosity=0, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_default_supervisor_account(self):
        out = self.init("--mot-de-passe-superviseur", "secret-fsu")
        user = User.objects.get(username="konin")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Superviseur"])
        self.assertFalse(user.is_superuser)
        self.assertIn("konin", out)  # affiché même avec -v 0
        self.assertNotIn("secret-fsu", out)
        self.assertTrue(self.client.login(username="konin", password="secret-fsu"))

    @mock.patch.dict("os.environ", {"SUPERVISEUR_MOT_DE_PASSE": ""})
    def test_not_created_without_password(self):
        err = StringIO()
        call_command("init_fsu", verbosity=0, stdout=StringIO(), stderr=err)
        self.assertFalse(User.objects.exists())
        self.assertIn("SUPERVISEUR_MOT_DE_PASSE", err.getvalue())

    def test_password_from_env_file(self):
        with mock.patch.dict("os.environ", {"SUPERVISEUR_MOT_DE_PASSE": "depuis-env"}):
            self.init()
        self.assertTrue(self.client.login(username="konin", password="depuis-env"))

    def test_given_credentials_are_used(self):
        self.init("--superviseur", "major", "--mot-de-passe-superviseur", "secret-fsu")
        self.assertTrue(self.client.login(username="major", password="secret-fsu"))

    def test_rerun_keeps_existing_account_and_password(self):
        self.init("--mot-de-passe-superviseur", "premier")
        out = self.init("--mot-de-passe-superviseur", "second")
        self.assertEqual(out, "")
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(self.client.login(username="konin", password="premier"))

    def test_not_created_when_a_supervisor_already_exists(self):
        self.init("--mot-de-passe-superviseur", "x")
        User.objects.get(username="konin").delete()
        other = User.objects.create_user("major")
        other.groups.add(Group.objects.get(name="Superviseur"))
        self.init("--mot-de-passe-superviseur", "x")
        self.assertFalse(User.objects.filter(username="konin").exists())

    def test_existing_username_without_role_is_left_alone(self):
        User.objects.create_user("konin", password="perso")
        self.init()
        user = User.objects.get(username="konin")
        self.assertFalse(user.groups.exists())
        self.assertTrue(user.check_password("perso"))


class AuditLogAccessTests(TestCase):
    """Le journal d'activité est réservé aux administrateurs et au superviseur."""

    @classmethod
    def setUpTestData(cls):
        call_command("init_fsu", verbosity=0, stdout=StringIO(), stderr=StringIO())

    def user(self, name, role=None, **flags):
        user = User.objects.create_user(name, password="x", **flags)
        if role:
            user.groups.add(Group.objects.get(name=role))
        return user

    def test_admin_and_supervisor_see_the_log(self):
        for user in (self.user("admin", is_superuser=True, is_staff=True), self.user("major", "Superviseur")):
            self.client.force_login(user)
            self.assertEqual(self.client.get("/journal/").status_code, 200, user)
            self.assertContains(self.client.get("/"), 'href="/journal/"')

    def test_other_roles_are_refused(self):
        for role in ("Caissier", "Pharmacie", "Consultation"):
            self.client.force_login(self.user(role.lower(), role))
            self.assertEqual(self.client.get("/journal/").status_code, 403, role)
            self.assertNotContains(self.client.get("/"), 'href="/journal/"')


class UserMenuTests(TestCase):
    def test_account_menu_top_right(self):
        call_command("init_fsu", verbosity=0, stdout=StringIO(), stderr=StringIO())
        user = User.objects.create_user("awa", password="x", first_name="Awa", last_name="KONE")
        user.groups.add(Group.objects.get(name="Caissier"))
        self.client.force_login(user)
        page = self.client.get("/")
        self.assertContains(page, 'class="user-menu"')
        self.assertContains(page, "<b>Awa KONE</b><small>Caissier</small>", html=False)
        self.assertContains(page, 'href="/mot-de-passe/"')
        self.assertContains(page, 'action="/deconnexion/"')


class TrimTextTests(TestCase):
    def test_single_line_text_is_trimmed_and_collapsed(self):
        from django import forms

        from core.forms import TrimTextMixin

        class F(TrimTextMixin, forms.Form):
            name = forms.CharField()
            notes = forms.CharField(widget=forms.Textarea)
            secret = forms.CharField(widget=forms.PasswordInput, strip=False)

            def clean_name(self):
                assert self.cleaned_data["name"] == "Jean Kouassi"  # déjà nettoyé pour les clean_<champ>()
                return self.cleaned_data["name"]

        f = F({"name": "  Jean   Kouassi ", "notes": "ligne 1\n\nligne 2", "secret": " mot  de passe "})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data, {"name": "Jean Kouassi", "notes": "ligne 1\n\nligne 2",
                                          "secret": " mot  de passe "})
        self.assertFalse(F({"name": "   ", "notes": "x", "secret": "x"}).is_valid())  # champ obligatoire vide
