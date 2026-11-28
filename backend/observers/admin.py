import datetime

from django import forms
from django.contrib import admin, messages

from accounts.models import User
from observers.models import ObserverProfile, ObserverScope, Pseudonym
from observers.services import create_observer
from observers.tokens import set_password_link


class ObserverProfileForm(forms.ModelForm):
    email = forms.EmailField(help_text="The observer signs in with this email.")

    class Meta:
        model = ObserverProfile
        fields = ["display_name", "organisation", "email", "level", "language", "scope", "expires_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["email"].initial = self.instance.user.email

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        others = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            others = others.exclude(pk=self.instance.user_id)
        if others.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


@admin.register(ObserverProfile)
class ObserverProfileAdmin(admin.ModelAdmin):
    form = ObserverProfileForm
    list_display = ["display_name", "organisation", "email", "level", "language", "expires_at", "active"]
    list_filter = ["level", "language", "organisation"]
    search_fields = ["display_name", "organisation", "user__email"]
    actions = ["extend_30_days", "deactivate", "activate", "new_set_password_link"]

    @admin.display(description="Email")
    def email(self, obj):
        return obj.user.email

    @admin.display(boolean=True, description="Active")
    def active(self, obj):
        return obj.is_usable

    def save_model(self, request, obj, form, change):
        if change:
            obj.save()
            user = obj.user
            user.email = form.cleaned_data["email"]
            user.save(update_fields=["email"])
            return
        profile, link = create_observer(
            name=obj.display_name, organisation=obj.organisation, email=form.cleaned_data["email"],
            level=obj.level, language=obj.language, expires_at=obj.expires_at, scope=obj.scope,
            created_by=request.user,
        )
        obj.pk = profile.pk
        obj.user = profile.user
        messages.warning(request, f"One-time set-password link (valid 48 hours, shown once): {link}")

    @admin.action(description="Extend by 30 days")
    def extend_30_days(self, request, queryset):
        for p in queryset:
            p.expires_at = max(p.expires_at, datetime.date.today()) + datetime.timedelta(days=30)
            p.save(update_fields=["expires_at"])
        self.message_user(request, f"Extended {queryset.count()} observer(s) by 30 days.")

    @admin.action(description="Deactivate (signs them out)")
    def deactivate(self, request, queryset):
        User.objects.filter(pk__in=queryset.values("user_id")).update(is_active=False)
        self.message_user(request, f"Deactivated {queryset.count()} observer(s).")

    @admin.action(description="Activate")
    def activate(self, request, queryset):
        User.objects.filter(pk__in=queryset.values("user_id")).update(is_active=True)
        self.message_user(request, f"Activated {queryset.count()} observer(s).")

    @admin.action(description="New set-password link")
    def new_set_password_link(self, request, queryset):
        for p in queryset:
            messages.warning(request, f"{p.display_name}: one-time link (48 hours, shown once): {set_password_link(p.user)}")


@admin.register(ObserverScope)
class ObserverScopeAdmin(admin.ModelAdmin):
    list_display = ["name", "all_businesses", "start_date", "end_date"]
    filter_horizontal = ["businesses"]


@admin.register(Pseudonym)
class PseudonymAdmin(admin.ModelAdmin):
    list_display = ["kind", "number", "created_at"]
    list_filter = ["kind"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
