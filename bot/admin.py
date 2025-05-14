from django.contrib import admin
from .models import Child, KindDeed, Reward, Parent

@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = ('name', 'telegram_id', 'total_points', 'created_at')
    search_fields = ('name', 'telegram_id')
    list_filter = ('created_at',)

@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    list_display = ('name', 'telegram_id', 'created_at')
    search_fields = ('name', 'telegram_id')
    list_filter = ('created_at',)
    filter_horizontal = ('children',)

@admin.register(KindDeed)
class KindDeedAdmin(admin.ModelAdmin):
    list_display = ('description', 'points', 'child', 'added_by', 'created_at')
    list_filter = ('created_at', 'added_by')
    search_fields = ('description',)
    autocomplete_fields = ('child', 'added_by')

@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ('name', 'points_required')
    search_fields = ('name',)