from django.urls import path
from . import views

urlpatterns=[
    path('callback',views.LineBotCallbackAPI.as_view()),
]