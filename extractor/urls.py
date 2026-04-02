from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("subscriptions/", views.subscription_plans, name="subscription_plans"),
    path("subscribe/<int:plan_id>/", views.subscribe_plan, name="subscribe_plan"),
    path("payment/<int:plan_id>/", views.dummy_payment, name="dummy_payment"),
    path("payment/success/<int:plan_id>/", views.payment_success, name="payment_success"),

    # Document routes
    path("document/<int:doc_id>/", views.document_detail, name="document_detail"),
    path("document/<int:doc_id>/download/json/", views.download_json, name="download_json"),
    path("document/<int:doc_id>/download/csv/", views.download_csv, name="download_csv"),

    # History
    path("history/", views.history, name="history"),

    # Compare
    path("compare/", views.compare_docs, name="compare_docs"),
]
