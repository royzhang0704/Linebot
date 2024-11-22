# Generated by Django 5.1.2 on 2024-11-04 11:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('urlbot', '0003_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='todolist',
            name='user',
        ),
        migrations.AddField(
            model_name='todolist',
            name='user_id',
            field=models.CharField(default='Unknown', max_length=255),
        ),
        migrations.DeleteModel(
            name='User',
        ),
    ]
