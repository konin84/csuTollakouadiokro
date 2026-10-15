from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, re_path

from caisse import views as caisse
from core import views as core
from rapports import views as rapports
from stock import views as stock

D = "<str:day>"

urlpatterns = [
    path("", core.dashboard, name="dashboard"),
    path("connexion/", auth_views.LoginView.as_view(template_name="core/login.html",
                                                     redirect_authenticated_user=True), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("mot-de-passe/", auth_views.PasswordChangeView.as_view(
        template_name="core/password.html", success_url="/"), name="password_change"),
    path("journal/", core.audit_log, name="audit_log"),
    re_path(r"^justificatifs/(?P<path>.+)$", core.protected_media, name="media"),

    # Caisse
    path("caisse/", caisse.session_list, name="session_list"),
    path("caisse/aujourdhui/", caisse.session_today, name="session_today"),
    path("caisse/ouvrir/", caisse.session_open, name="session_open"),
    path(f"caisse/{D}/", caisse.session_detail, name="session_detail"),
    path(f"caisse/{D}/acte/<int:entry_id>/", caisse.entry_update, name="entry_update"),
    path(f"caisse/{D}/depense/", caisse.expense_add, name="expense_add"),
    path(f"caisse/{D}/depense/<int:pk>/supprimer/", caisse.expense_delete, name="expense_delete"),
    path(f"caisse/{D}/vente/", caisse.sale_add, name="sale_add"),
    path(f"caisse/{D}/vente/<int:pk>/supprimer/", caisse.sale_delete, name="sale_delete"),
    path(f"caisse/{D}/cloturer/", caisse.session_close, name="session_close"),
    path(f"caisse/{D}/valider/", caisse.session_validate, name="session_validate"),
    path(f"caisse/{D}/rouvrir/", caisse.session_reopen, name="session_reopen"),
    path("versements/", caisse.deposit_list, name="deposit_list"),
    path("versements/ajouter/", caisse.deposit_add, name="deposit_add"),
    path("versements/<int:pk>/", caisse.deposit_edit, name="deposit_edit"),

    # Pharmacie / stock
    path("stock/", stock.product_list, name="product_list"),
    path("stock/produit/nouveau/", stock.product_new, name="product_new"),
    path("stock/produit/<int:pk>/", stock.product_detail, name="product_detail"),
    path("stock/commandes/", stock.order_list, name="order_list"),
    path("stock/commandes/nouvelle/", stock.order_new, name="order_new"),
    path("stock/commandes/<int:pk>/", stock.order_detail, name="order_detail"),
    path("stock/commandes/<int:pk>/ligne/<int:line_id>/supprimer/", stock.order_line_delete,
         name="order_line_delete"),
    path("stock/commandes/<int:pk>/statut/", stock.order_status, name="order_status"),
    path("stock/commandes/<int:pk>/reception/", stock.order_receive, name="order_receive"),
    path("stock/inventaire/", stock.inventory, name="inventory"),
    path("stock/sortie/", stock.loss, name="stock_loss"),

    # Rapports
    path("rapports/mensuel/", rapports.monthly, name="report_monthly"),
    path("rapports/mensuel/excel/", rapports.monthly_xlsx, name="report_monthly_xlsx"),
    path("rapports/annuel/", rapports.annual, name="report_annual"),
    path("rapports/annuel/excel/", rapports.annual_xlsx, name="report_annual_xlsx"),

    path("admin/", admin.site.urls),
]
