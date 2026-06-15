"""
Migration to add carousel/universal send v2 fields to SchedulerJob.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduler', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedulerjob',
            name='template_type',
            field=models.CharField(
                default='standard',
                help_text='Template type: standard or carousel',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='schedulerjob',
            name='header_data',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Full header component data (type, url, text, etc.)',
            ),
        ),
        migrations.AddField(
            model_name='schedulerjob',
            name='cards_json',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Carousel cards array. Each card: {header, bodyParams, buttonParams}',
            ),
        ),
    ]
