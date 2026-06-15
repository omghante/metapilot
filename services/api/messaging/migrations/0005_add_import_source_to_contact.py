from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0004_add_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='contact',
            name='import_source',
            field=models.ForeignKey(
                blank=True,
                help_text='The import batch this contact was created from',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='contacts',
                to='messaging.contactimport',
            ),
        ),
    ]
