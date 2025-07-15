from django.urls import path
from . import views

urlpatterns = [
    path('mark-attendance/', views.mark_attendance, name='mark_attendance'),
    path('attendance-list/', views.attendance_list, name='attendance_list'),
    path('download-report/', views.download_attendance_report, name='download_report'),
    path('report-view/', views.attendance_report_view, name='report_view'),
]
