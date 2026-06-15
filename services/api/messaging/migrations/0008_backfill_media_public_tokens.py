"""
Backfill public_token for existing MediaAsset records.
"""
import secrets
from django.db import migrations


def backfill_tokens(apps, schema_editor):
    MediaAsset = apps.get_model('messaging', 'MediaAsset')
    assets = MediaAsset.objects.filter(public_token='')
    for asset in assets:
        asset.public_token = secrets.token_hex(16)
    MediaAsset.objects.bulk_update(assets, ['public_token'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0007_add_public_token_to_media_asset'),
    ]

    operations = [
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop),
    ]
