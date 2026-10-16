"""Initialise une installation : rôles, compte superviseur, établissement, actes et
tarifs, règles de commission, catégories de dépenses, comptes bancaires.

La commande peut être relancée sans risque : elle ne crée que ce qui manque.

    python manage.py init_fsu --nom "Centre de Santé Urbain (CSU) de Tollakouadiokro" --demarrage 2026-01-01

Compte superviseur : créé seulement si aucun utilisateur n'a le rôle Superviseur.
Identifiant « konin » par défaut (--superviseur) ; mot de passe : --mot-de-passe-superviseur,
sinon SUPERVISEUR_MOT_DE_PASSE (demandé par installer.ps1). Aucun mot de passe n'est écrit
dans le code : sans mot de passe, le compte n'est pas créé.
"""
import os
from datetime import date

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from caisse.models import (FUND_ENTREE, FUND_PHARMA, Act, ActPrice, BankAccount, CommissionRule,
                           ExpenseCategory, name_key)
from core.models import Facility
from core.roles import ALL_ROLES, SUPERVISEUR

# code, libellé, catégorie, caisse, mode, labo, prix
ACTS = [
    ("consultation-curative", "Consultations curatives", "CONSULT", FUND_ENTREE, "QTE", False, 1000),
    ("consultation-eleves", "Consultations élèves", "CONSULT", FUND_ENTREE, "QTE", False, 200),
    ("cpn", "CPN", "MATERNITE", FUND_ENTREE, "QTE", False, 1000),
    ("accouchement", "Accouchements", "MATERNITE", FUND_ENTREE, "QTE", False, 5000),
    ("accouchement-domicile", "Accouchements à domicile", "MATERNITE", FUND_ENTREE, "QTE", False, 7000),
    ("mise-pose", "Mise + pause", "MATERNITE", FUND_ENTREE, "QTE", False, 2500),
    ("consultation-gyneco", "Consultations gynécologiques", "CONSULT", FUND_ENTREE, "QTE", False, 5000),
    ("echographie", "Échographie", "IMAGERIE", FUND_PHARMA, "QTE", False, 10000),
    ("carnet-mere-enfant", "Carnet mère-enfant", "DOCUMENTS", FUND_ENTREE, "QTE", False, 500),
    ("carnet-individuel", "Carnet individuel", "DOCUMENTS", FUND_ENTREE, "QTE", False, 200),
    ("pansement", "Pansement", "SOINS", FUND_ENTREE, "QTE", False, 200),
    ("controle-ta", "Contrôle TA", "SOINS", FUND_ENTREE, "QTE", False, 200),
    ("injections", "Injections", "SOINS", FUND_ENTREE, "QTE", False, 200),
    ("gant", "Gant", "SOINS", FUND_ENTREE, "QTE", False, 200),
    ("petite-chirurgie", "Petite chirurgie", "SOINS", FUND_ENTREE, "QTE", False, 1000),
    ("bandelette-urinaire", "Bandelette urinaire", "SOINS", FUND_ENTREE, "QTE", False, 100),
    ("ambulance", "Ambulance", "TRANSPORT", FUND_ENTREE, "QTE", False, 3000),
    ("avortement-spontane", "Avortement spontané", "MATERNITE", FUND_ENTREE, "QTE", False, 3000),
]

EXPENSE_CATEGORIES = [
    ("Ristourne médecin (échographie)", FUND_PHARMA, 10),
    ("Ristourne SFDE (échographie)", FUND_PHARMA, 20),
    ("Dépenses pharmacie divers", FUND_PHARMA, 30),
    ("Consommables médicaux (alcool, coton, solutés…)", FUND_ENTREE, 40),
    ("Matériel médical", FUND_ENTREE, 50),
    ("Fournitures de bureau (rames, encre…)", FUND_ENTREE, 60),
    ("Carnets et reçus", FUND_ENTREE, 70),
    ("Internet et téléphone", FUND_ENTREE, 80),
    ("Entretien (espaces verts, nettoyage…)", FUND_ENTREE, 90),
    ("Carburant et transport", FUND_ENTREE, 100),
    ("Autres dépenses", FUND_ENTREE, 200),
]


class Command(BaseCommand):
    help = "Initialise les données de base de l'application (sans écraser l'existant)."

    def add_arguments(self, parser):
        parser.add_argument("--nom", default="Centre de Santé Urbain (CSU) de Tollakouadiokro", help="Nom de l'établissement")
        parser.add_argument("--demarrage", default="2026-01-01",
                            help="Date à partir de laquelle les tarifs et commissions s'appliquent (AAAA-MM-JJ)")
        parser.add_argument("--superviseur", default="konin",
                            help="Identifiant du compte superviseur créé automatiquement")
        parser.add_argument("--mot-de-passe-superviseur", dest="supervisor_password",
                            default=os.environ.get("SUPERVISEUR_MOT_DE_PASSE", ""),
                            help="Mot de passe de ce compte (sinon SUPERVISEUR_MOT_DE_PASSE)")

    def handle(self, *args, **opts):
        start = date.fromisoformat(opts["demarrage"])

        for role in ALL_ROLES:
            Group.objects.get_or_create(name=role)
        self.ensure_supervisor(opts["superviseur"], opts["supervisor_password"])

        facility = Facility.objects.order_by("id").first()
        if facility is None:
            Facility.objects.create(name=opts["nom"], short_name="FSU", opening_date=start)
            if opts["verbosity"]:
                self.stdout.write(f"Établissement créé : {opts['nom']}")

        for order, (code, name, cat, fund, mode, is_lab, price) in enumerate(ACTS, start=1):
            if Act.objects.filter(name_key=name_key(name)).exclude(code=code).exists():
                continue  # même libellé déjà créé dans les Paramètres (autre code) : pas de doublon
            act, created = Act.objects.get_or_create(
                code=code,
                defaults=dict(name=name, category=cat, fund=fund, entry_mode=mode, is_lab=is_lab, order=order * 10),
            )
            if created and price is not None:
                ActPrice.objects.create(act=act, price=price, valid_from=start)

        if not CommissionRule.objects.exists():
            CommissionRule.objects.create(name="Commission prescripteurs", beneficiary="Prescripteurs",
                                          rate=15, retained=False, valid_from=start, order=10)
            CommissionRule.objects.create(name="Commission laboratoire partenaire",
                                          beneficiary="Laboratoire partenaire", rate=60, retained=False,
                                          valid_from=start, order=20)
            CommissionRule.objects.create(name="Part ONG AIP", beneficiary="ONG AIP", rate=25, retained=True,
                                          valid_from=start, order=30)

        for name, fund, order in EXPENSE_CATEGORIES:
            ExpenseCategory.objects.get_or_create(name=name, defaults=dict(default_fund=fund, order=order))

        if not BankAccount.objects.exists():
            BankAccount.objects.create(name="BOA", bank="BOA", fund="", number="")
            BankAccount.objects.create(name="Banque Populaire", bank="Banque Populaire", fund=FUND_ENTREE)

        if opts["verbosity"]:
            self.stdout.write(self.style.SUCCESS("Données de base en place."))

    def ensure_supervisor(self, username, password):
        group = Group.objects.get(name=SUPERVISEUR)
        if group.user_set.exists():
            return
        if User.objects.filter(username=username).exists():
            self.stderr.write(self.style.WARNING(
                f"Aucun superviseur, mais l'identifiant « {username} » est déjà pris : "
                "attribuez le rôle Superviseur à un compte dans Paramètres."))
            return
        if not password:
            self.stderr.write(self.style.WARNING(
                f"Compte superviseur « {username} » non créé : indiquez son mot de passe avec "
                "--mot-de-passe-superviseur ou la variable SUPERVISEUR_MOT_DE_PASSE."))
            return
        user =User.objects.create_user(username, password=password)
        user.groups.add(group)
        # toujours affiché, même avec -v 0 (mise à jour) : le compte doit être connu
        self.stdout.write(self.style.SUCCESS(
            f"Compte superviseur créé : identifiant « {username} » (mot de passe à changer à la première connexion)"))
