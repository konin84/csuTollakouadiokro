"""
Paramètres FSU Caisse.

Toute la configuration propre à une installation se fait dans le fichier
`.env` (à côté de manage.py) ou via des variables d'environnement :

    SECRET_KEY=...            (généré par le script d'installation)
    DEBUG=0
    ALLOWED_HOSTS=*           (réseau local : on accepte toutes les adresses)
    DATABASE_URL=             (vide = SQLite ; ex. postgres://user:pass@localhost/fsu)
    DATA_DIR=                 (dossier des données : base, justificatifs, sauvegardes)
    BACKUP_COPY_DIR=          (copie supplémentaire des sauvegardes, ex. E:\\SauvegardesFSU)
    SUPERVISEUR_MOT_DE_PASSE= (mot de passe du compte superviseur créé par init_fsu ;
                               en général saisi pendant installer.ps1, pas conservé ici)
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Lecture minimale d'un fichier .env (CLE=valeur), sans dépendance externe."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).lower() in ("1", "true", "yes", "oui")


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", DATA_DIR / "sauvegardes"))
BACKUP_COPY_DIR = os.environ.get("BACKUP_COPY_DIR", "")
BACKUP_KEEP_DAYS = int(os.environ.get("BACKUP_KEEP_DAYS", "30"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "caisse",
    "stock",
    "rapports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.CurrentUserMiddleware",
    "core.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.app_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Base de données -------------------------------------------------------
# Par défaut : SQLite en mode WAL. Largement suffisant pour un centre de santé
# (quelques postes simultanés) et la sauvegarde se résume à un fichier.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "fsu_caisse.sqlite3",
            "OPTIONS": {
                "transaction_mode": "IMMEDIATE",
                "timeout": 20,
                "init_command": (
                    "PRAGMA journal_mode=WAL;"
                    "PRAGMA synchronous=NORMAL;"
                    "PRAGMA foreign_keys=ON;"
                ),
            },
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Abidjan"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if DEBUG:
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# Justificatifs (reçus, bordereaux) : servis uniquement aux utilisateurs connectés.
MEDIA_ROOT = DATA_DIR / "justificatifs"
MEDIA_URL = "/justificatifs/"
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_AGE = 12 * 3600

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(DATA_DIR / "fsu_caisse.log"),
            "maxBytes": 2 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["file", "console"], "level": "WARNING"},
}
