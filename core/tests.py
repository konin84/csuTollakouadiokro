import re
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase


class SupervisorAccountTests(TestCase):
    def init(self, *args):
        out = StringIO()
        call_command("init_fsu", *args, verbosity=0, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_supervisor_created_with_generated_password(self):
        out = self.init()
        user = User.objects.get(username="superviseur")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Superviseur"])
        self.assertFalse(user.is_superuser)
        password = re.search(r"Mot de passe : (\S+)", out).group(1)  # affiché même avec -v 0
        self.assertEqual(len(password), 10)
        self.assertTrue(self.client.login(username="superviseur", password=password))

    def test_given_password_is_used_and_not_printed(self):
        out = self.init("--superviseur", "major", "--mot-de-passe-superviseur", "secret-fsu")
        self.assertNotIn("secret-fsu", out)
        self.assertTrue(self.client.login(username="major", password="secret-fsu"))

    def test_rerun_keeps_existing_account_and_password(self):
        self.init("--mot-de-passe-superviseur", "premier")
        out = self.init("--mot-de-passe-superviseur", "second")
        self.assertEqual(out, "")
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(self.client.login(username="superviseur", password="premier"))

    def test_not_created_when_a_supervisor_already_exists(self):
        self.init("--mot-de-passe-superviseur", "x")
        User.objects.get(username="superviseur").delete()
        other = User.objects.create_user("major")
        other.groups.add(Group.objects.get(name="Superviseur"))
        self.init()
        self.assertFalse(User.objects.filter(username="superviseur").exists())

    def test_existing_username_without_role_is_left_alone(self):
        User.objects.create_user("superviseur", password="perso")
        self.init()
        user = User.objects.get(username="superviseur")
        self.assertFalse(user.groups.exists())
        self.assertTrue(user.check_password("perso"))
