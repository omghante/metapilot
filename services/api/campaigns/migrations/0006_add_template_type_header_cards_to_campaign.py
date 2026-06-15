"""
Add template_type, header_data, cards_json to Campaign model.

Mirrors the same fields already on CampaignMessage, enabling campaign-level
carousel/media template scheduling without losing metadata when creating jobs.

Existing rows receive sensible non-null defaults:
  template_type  → 'standard'
  header_data    → NULL  (nullable)
  cards_json     → NULL  (nullable)
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0005_add_template_type_header_cards_to_campaign_message'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='template_type',
            field=models.CharField(
                blank=True,
                default='standard',
                help_text='Template type: standard or carousel',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='campaign',
            name='header_data',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text='Header media: {"type": "image"|"video", "url": "..."}',
            ),
        ),
        migrations.AddField(
            model_name='campaign',
            name='cards_json',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text='Carousel cards: [{"header": {...}, "bodyParams": [...], "buttonParams": [...]}]',
            ),
        ),
    ]
