# Generated by Django 5.1.2 on 2024-10-26 08:57

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Url',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('origin_url', models.CharField(max_length=255, unique=True)),
                ('short_url', models.CharField(max_length=15, unique=True)),
                ('create_at', models.DateField(auto_now_add=True)),
            ],
        ),
    ]
