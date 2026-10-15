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
