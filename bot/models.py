from django.db import models

class Child(models.Model):
    """Модель ребенка"""
    telegram_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    total_points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.total_points} баллов)"

class Parent(models.Model):
    """Модель родителя"""
    telegram_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    password = models.CharField(max_length=100, blank=True, null=True)  # Простой пароль для авторизации
    children = models.ManyToManyField(Child, related_name='parents')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (Родитель)"

class KindDeed(models.Model):
    """Модель доброго дела"""
    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name='deeds')
    description = models.TextField()
    points = models.IntegerField()
    added_by = models.ForeignKey(Parent, on_delete=models.SET_NULL, null=True, blank=True, related_name='added_deeds')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.description} ({self.points} баллов)"

class Reward(models.Model):
    """Модель наград"""
    name = models.CharField(max_length=200)
    points_required = models.IntegerField()
    description = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.name} ({self.points_required} баллов)"