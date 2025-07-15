from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Employee, Attendance
from django.utils import timezone
from django.utils.timezone import localtime
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.http import HttpResponse
from django.contrib.auth import logout, authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings
import csv
from datetime import datetime, timedelta

today = timezone.localtime(timezone.now()).date()

def is_security(user):
    return user.groups.filter(name='Security').exists()

@login_required
def mark_attendance(request):
    # Remove the security check since all employees should be able to mark their own attendance
    try:
        # Get the employee record for the currently logged-in user
        employee = Employee.objects.get(user=request.user, is_active=True)
        today = timezone.localtime(timezone.now()).date()

        if request.method == 'POST':
            action = request.POST.get('action')

            if action == 'time_in':
                # Check if already marked present today
                if Attendance.objects.filter(employee=employee, date=today).exists():
                    messages.warning(request, "You are already marked present today.")
                else:
                    current_time = localtime(timezone.now()).time()
                    late_reason = request.POST.get('late_reason', '').strip()
                    
                    # Check if time is after 8:00 AM
                    if current_time.hour >= 8:
                        status = 'Late'
                        if not late_reason:
                            # Return form with error if no reason provided for late attendance
                            messages.error(request, "Please provide a reason for being late.")
                            attendance = Attendance.objects.filter(employee=employee, date=today).first()
                            return render(request, 'attendance/mark_attendance.html', {
                                'employee': employee,
                                'attendance': attendance,
                                'is_security': is_security(request.user)
                            })
                    else:
                        status = 'Present'
                    
                    Attendance.objects.create(
                        employee=employee,
                        date=today,
                        time_in=current_time,
                        status=status,
                        late_reason=late_reason if status == 'Late' else None
                    )
                    
                    if status == 'Late':
                        messages.success(request, f"Attendance marked as late. Reason: {late_reason}")
                    else:
                        messages.success(request, "Successfully marked your attendance.")

            elif action == 'time_out':
                attendance = Attendance.objects.filter(employee=employee, date=today).first()
                
                if attendance:
                    if attendance.time_out:
                        messages.warning(request, "You have already been marked out today.")
                    else:
                        current_time_out = localtime(timezone.now()).time()
                        attendance.time_out = current_time_out
                        attendance.save()
                        messages.success(request, "Successfully marked your time out.")
                else:
                    messages.warning(request, "You haven't been marked in yet today.")
        
        # Get the current user's attendance record for display
        attendance = Attendance.objects.filter(employee=employee, date=today).first()
        
        return render(request, 'attendance/mark_attendance.html', {
            'employee': employee,
            'attendance': attendance,
            'is_security': is_security(request.user)
        })
        
    except Employee.DoesNotExist:
        messages.error(request, "You don't have an employee record in the system. Please contact your administrator.")
        return redirect('login')

@login_required
def attendance_list(request):
    if not is_security(request.user):
        return HttpResponseForbidden("You don't have permission to access this page.")

    today = timezone.localtime(timezone.now()).date()
    attendances = Attendance.objects.filter(date=today).select_related('employee', 'employee__user').order_by('employee__user__first_name')

    context = {
        'attendances': attendances,
        'today': today.strftime("%Y-%m-%d"),  # Format date for display
        'is_security': is_security(request.user)
    }
    return render(request, 'attendance/attendance_list.html', context)


@login_required
def download_attendance_report(request):
    # Get date range from request (default to last 7 days)
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)

    if request.method == 'POST':
        start_date = datetime.strptime(request.POST.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.POST.get('end_date'), '%Y-%m-%d').date()

    # Get filtered attendance data
    attendances = Attendance.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    ).select_related('employee__user').order_by('date', 'employee__user__first_name')

    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="attendance_report_{start_date}_to_{end_date}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Date', 'Employee ID', 'Employee Name',
        'Department', 'Time In', 'Time Out', 'Status', 'Late Reason'
    ])

    for att in attendances:
        writer.writerow([
            att.date.strftime('%Y-%m-%d'),
            att.employee.employee_id,
            att.employee.user.get_full_name(),
            att.employee.department,
            att.time_in.strftime('%H:%M') if att.time_in else '',
            att.time_out.strftime('%H:%M') if att.time_out else '',
            att.status,
            att.late_reason if att.late_reason else ''
        ])

    return response

@login_required
def attendance_report_view(request):
    # Get date range from request (default to last 7 days)
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)

    if request.method == 'POST':
        start_date = datetime.strptime(request.POST.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.POST.get('end_date'), '%Y-%m-%d').date()

    # Get filtered attendance data
    attendances = Attendance.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    ).select_related('employee__user').order_by('date', 'employee__user__first_name')

    # Calculate statistics
    total_records = attendances.count()
    present_count = attendances.filter(status='Present').count()
    late_count = attendances.filter(status='Late').count()
    
    # Calculate absent count (total active employees * days - total records)
    total_employees = Employee.objects.filter(is_active=True).count()
    date_range_days = (end_date - start_date).days + 1
    expected_records = total_employees * date_range_days
    absent_count = expected_records - total_records

    context = {
        'attendances': attendances,
        'start_date': start_date,
        'end_date': end_date,
        'is_security': is_security(request.user),
        'total_records': total_records,
        'present_count': present_count,
        'late_count': late_count,
        'absent_count': absent_count,
    }
    return render(request, 'attendance/attendance_report_view.html', context)

from django.http import HttpRequest

def custom_logout(request: HttpRequest):
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('login')

def custom_login(request):
    if request.method == 'POST':
        print(f"POST data: {request.POST}")
        print(f"CSRF token in POST: {request.POST.get('csrfmiddlewaretoken')}")
        print(f"CSRF token in request: {request.META.get('CSRF_COOKIE')}")
        
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f"Welcome back, {user.username}!")
                # Redirect to next page or default
                next_url = request.POST.get('next') or request.GET.get('next') or '/mark-attendance/'
                return redirect(next_url)
            else:
                messages.error(request, "Invalid username or password.")
        else:
            print(f"Form errors: {form.errors}")
            messages.error(request, "Please correct the errors below.")
    else:
        form = AuthenticationForm()
    
    return render(request, 'attendance/login.html', {'form': form})

