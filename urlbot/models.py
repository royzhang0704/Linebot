from django.db import models
from django.utils import timezone

class Todolist(models.Model):
    status_choices = [
        ('pending', '未完成'),
        ('completed', '完成')
    ]

    title = models.CharField(
        max_length=50,
        verbose_name="待辦事項名稱",
        null = True,
        blank = True
    )

    user_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Line用戶ID"
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="創建時間"
    )

    status = models.CharField(
        max_length=20,
        choices=status_choices,
        default='pending',
        verbose_name="待辦事項狀態"
    )

    class Meta:
        verbose_name = '待辦事項'
        verbose_name_plural = '待辦事項列表'
        ordering = ['created_at']

    def __str__(self):
        return self.title
