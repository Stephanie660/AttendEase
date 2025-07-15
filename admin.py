from django.contrib import admin
from .models import Employee, Attendance
from django.utils.html import format_html
import csv
from django.http import HttpResponse
from django.urls import path
from django.shortcuts import render
from django import forms
from datetime import date, timedelta
from django.db.models import Count, Q
from django.utils import timezone
from django.contrib.admin import SimpleListFilter

class DepartmentFilter(SimpleListFilter):
    title = 'Department'
    parameter_name = 'department'

    def lookups(self, request, model_admin):
        departments = Employee.objects.values_list('department', flat=True).distinct()
        return [(dept, dept) for dept in departments]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(employee__department=self.value())
        return queryset

class DateRangeFilter(SimpleListFilter):
    title = 'Date Range'
    parameter_name = 'date_range'

    def lookups(self, request, model_admin):
        return [
            ('today', 'Today'),
            ('yesterday', 'Yesterday'),
            ('this_week', 'This Week'),
            ('last_week', 'Last Week'),
            ('this_month', 'This Month'),
            ('last_month', 'Last Month'),
        ]

    def queryset(self, request, queryset):
        today = timezone.localtime(timezone.now()).date()
        
        if self.value() == 'today':
            return queryset.filter(date=today)
        if self.value() == 'yesterday':
            return queryset.filter(date=today - timedelta(days=1))
        if self.value() == 'this_week':
            start_of_week = today - timedelta(days=today.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            return queryset.filter(date__gte=start_of_week, date__lte=end_of_week)
        if self.value() == 'last_week':
            end_of_last_week = today - timedelta(days=today.weekday() + 1)
            start_of_last_week = end_of_last_week - timedelta(days=6)
            return queryset.filter(date__gte=start_of_last_week, date__lte=end_of_last_week)
        if self.value() == 'this_month':
            return queryset.filter(date__year=today.year, date__month=today.month)
        if self.value() == 'last_month':
            if today.month == 1:  # January
                last_month = 12  # December
                year = today.year - 1
            else:
                last_month = today.month - 1
                year = today.year
            return queryset.filter(date__year=year, date__month=last_month)
        return queryset

class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee_id', 'get_full_name', 'department', 'position', 'phone_number', 'is_active', 'attendance_count')
    list_filter = ('is_active', 'department')
    search_fields = ('employee_id', 'user__first_name', 'user__last_name', 'department', 'position')
    readonly_fields = ('attendance_count',)
    
    def get_full_name(self, obj):
        return obj.user.get_full_name()
    get_full_name.short_description = 'Employee Name'
    
    @admin.display(description='Attendance Records')
    def attendance_count(self, obj):
        count = Attendance.objects.filter(employee=obj).count()
        return format_html('<a href="/admin/attendance/attendance/?employee__id__exact={}">{} records</a>', obj.id, count)

class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'time_in', 'time_out', 'duration', 'status', 'late_reason_short', 'day_of_week')
    list_filter = (DateRangeFilter, 'status', DepartmentFilter, 'employee__user')
    search_fields = ('employee__user__first_name', 'employee__user__last_name', 'employee__employee_id', 'late_reason')
    date_hierarchy = 'date'
    
    change_list_template = "admin/attendance_change_list.htm"
    actions = ['mark_as_present', 'mark_as_absent', 'mark_as_late']
    
    def late_reason_short(self, obj):
        if obj.late_reason:
            return obj.late_reason[:50] + "..." if len(obj.late_reason) > 50 else obj.late_reason
        return "-"
    late_reason_short.short_description = 'Late Reason'
    
    @admin.display(description='Day')
    def day_of_week(self, obj):
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        return days[obj.date.weekday()]
    
    @admin.display(description='Duration')
    def duration(self, obj):
        if obj.time_in and obj.time_out:
            # Calculate duration in hours and minutes
            time_in_minutes = obj.time_in.hour * 60 + obj.time_in.minute
            time_out_minutes = obj.time_out.hour * 60 + obj.time_out.minute
            duration_minutes = time_out_minutes - time_in_minutes
            
            if duration_minutes < 0:
                return "Invalid"
            
            hours = duration_minutes // 60
            minutes = duration_minutes % 60
            
            return f"{hours}h {minutes}m"
        return "-"
    
    @admin.action(description="Mark selected attendances as Present")
    def mark_as_present(self, request, queryset):
        queryset.update(status='Present')
    
    @admin.action(description="Mark selected attendances as Absent")
    def mark_as_absent(self, request, queryset):
        queryset.update(status='Absent')
    
    @admin.action(description="Mark selected attendances as Late")
    def mark_as_late(self, request, queryset):
        queryset.update(status='Late')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('report/', self.admin_site.admin_view(self.generate_report), name='attendance-report'),
            path('summary/', self.admin_site.admin_view(self.attendance_summary), name='attendance-summary'),
        ]
        return custom_urls + urls

    from django.http import HttpRequest

    def generate_report(self, request: 'HttpRequest'):
        if request.method == 'POST':
            form = ReportForm(request.POST)
            if form.is_valid():
                start_date = form.cleaned_data['start_date']
                end_date = form.cleaned_data['end_date']
                department = form.cleaned_data.get('department')
                report_type = form.cleaned_data.get('report_type', 'detailed')

                # Generate CSV
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = f'attachment; filename="attendance_report_{start_date}_to_{end_date}.csv"'

                writer = csv.writer(response)
                
                # Filter by department if specified
                attendances = Attendance.objects.filter(
                    date__gte=start_date,
                    date__lte=end_date
                ).select_related('employee', 'employee__user')
                
                if department:
                    attendances = attendances.filter(employee__department=department)
                
                if report_type == 'detailed':
                    writer.writerow(['Employee ID', 'Employee Name', 'Department', 'Date', 'Day', 'Time In', 'Time Out', 'Duration', 'Status', 'Late Reason'])
                    
                    for att in attendances.order_by('date', 'employee__user__first_name'):
                        # Calculate duration
                        duration = "-"
                        if att.time_in and att.time_out:
                            time_in_minutes = att.time_in.hour * 60 + att.time_in.minute
                            time_out_minutes = att.time_out.hour * 60 + att.time_out.minute
                            duration_minutes = time_out_minutes - time_in_minutes
                            
                            if duration_minutes >= 0:
                                hours = duration_minutes // 60
                                minutes = duration_minutes % 60
                                duration = f"{hours}h {minutes}m"
                        
                        writer.writerow([
                            att.employee.employee_id,
                            att.employee.user.get_full_name(),
                            att.employee.department,
                            att.date.strftime('%Y-%m-%d'),
                            att.date.strftime('%A'),
                            att.time_in.strftime('%H:%M') if att.time_in else '-',
                            att.time_out.strftime('%H:%M') if att.time_out else '-',
                            duration,
                            att.status,
                            att.late_reason if att.late_reason else '-'
                        ])
                else:  # summary report
                    writer.writerow(['Employee ID', 'Employee Name', 'Department', 'Days Present', 'Days Absent', 'Days Late', 'Average Hours'])
                    
                    employees = Employee.objects.filter(attendance__date__gte=start_date, attendance__date__lte=end_date).distinct()
                    if department:
                        employees = employees.filter(department=department)
                    
                    for emp in employees:
                        emp_attendances = attendances.filter(employee=emp)
                        present_count = emp_attendances.filter(status='Present').count()
                        absent_count = emp_attendances.filter(status='Absent').count()
                        late_count = emp_attendances.filter(status='Late').count()
                        
                        # Calculate average hours
                        total_minutes = 0
                        valid_days = 0
                        
                        for att in emp_attendances:
                            if att.time_in and att.time_out:
                                time_in_minutes = att.time_in.hour * 60 + att.time_in.minute
                                time_out_minutes = att.time_out.hour * 60 + att.time_out.minute
                                duration_minutes = time_out_minutes - time_in_minutes
                                
                                if duration_minutes >= 0:
                                    total_minutes += duration_minutes
                                    valid_days += 1
                        
                        avg_hours = "-"
                        if valid_days > 0:
                            avg_minutes = total_minutes / valid_days
                            avg_minutes_int = int(avg_minutes)
                            avg_hours = f"{avg_minutes_int // 60}h {avg_minutes_int % 60}m"
                        
                        writer.writerow([
                            emp.employee_id,
                            emp.user.get_full_name(),
                            emp.department,
                            present_count,
                            absent_count,
                            late_count,
                            avg_hours,
                        ])

                return response
        else:
            form = ReportForm(initial={
                'start_date': date.today().replace(day=1),
                'end_date': date.today(),
                'report_type': 'detailed'
            })

        # Get all departments for the dropdown
        departments = Employee.objects.values_list('department', flat=True).distinct()
        
        context = {
            'form': form,
            'title': 'Generate Attendance Report',
            'departments': departments
        }
        return render(request, 'admin/attendance_report.html', context)
        
    from django.http import HttpRequest

    def attendance_summary(self, request: 'HttpRequest'):
        today = timezone.localtime(timezone.now()).date()
        
        # Get summary statistics
        total_employees = Employee.objects.filter(is_active=True).count()
        present_today = Attendance.objects.filter(date=today).count()
        absent_today = total_employees - present_today
        late_today = Attendance.objects.filter(date=today, status='Late').count()
        
        # Department wise attendance
        departments = Employee.objects.values_list('department', flat=True).distinct()
        department_stats = []
        
        for dept in departments:
            dept_total = Employee.objects.filter(department=dept, is_active=True).count()
            dept_present = Attendance.objects.filter(date=today, employee__department=dept).count()
            dept_absent = dept_total - dept_present
            dept_late = Attendance.objects.filter(date=today, employee__department=dept, status='Late').count()
            
            department_stats.append({
                'name': dept,
                'total': dept_total,
                'present': dept_present,
                'absent': dept_absent,
                'late': dept_late,
                'present_percent': round((dept_present / dept_total) * 100, 1) if dept_total > 0 else 0
            })
        
        context = {
            'title': 'Attendance Summary',
            'today': today,
            'total_employees': total_employees,
            'present_today': present_today,
            'absent_today': absent_today,
            'late_today': late_today,
            'present_percent': round((present_today / total_employees) * 100, 1) if total_employees > 0 else 0,
            'department_stats': department_stats
        }
        
        return render(request, 'admin/attendance_summary.html', context)

class ReportForm(forms.Form):
    start_date = forms.DateField(label='Start Date', widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(label='End Date', widget=forms.DateInput(attrs={'type': 'date'}))
    department = forms.CharField(label='Department', required=False)
    REPORT_CHOICES = [
        ('detailed', 'Detailed Report'),
        ('summary', 'Summary Report')
    ]
    report_type = forms.ChoiceField(label='Report Type', choices=REPORT_CHOICES, initial='detailed')

admin.site.register(Employee, EmployeeAdmin)
admin.site.register(Attendance, AttendanceAdmin)