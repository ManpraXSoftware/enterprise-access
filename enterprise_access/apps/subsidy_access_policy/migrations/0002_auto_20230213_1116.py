# Generated by Django 3.2.16 on 2023-02-13 11:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subsidy_access_policy', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cappedenrollmentlearnercreditaccesspolicy',
            name='catalog_uuid',
            field=models.UUIDField(db_index=True),
        ),
        migrations.AlterField(
            model_name='cappedenrollmentlearnercreditaccesspolicy',
            name='group_uuid',
            field=models.UUIDField(db_index=True),
        ),
        migrations.AlterField(
            model_name='perlearnerenrollmentcaplearnercreditaccesspolicy',
            name='catalog_uuid',
            field=models.UUIDField(db_index=True),
        ),
        migrations.AlterField(
            model_name='perlearnerenrollmentcaplearnercreditaccesspolicy',
            name='group_uuid',
            field=models.UUIDField(db_index=True),
        ),
        migrations.AlterField(
            model_name='perlearnerspendcaplearnercreditaccesspolicy',
            name='catalog_uuid',
            field=models.UUIDField(db_index=True),
        ),
        migrations.AlterField(
            model_name='perlearnerspendcaplearnercreditaccesspolicy',
            name='group_uuid',
            field=models.UUIDField(db_index=True),
        ),
        migrations.AlterField(
            model_name='subscriptionaccesspolicy',
            name='catalog_uuid',
            field=models.UUIDField(db_index=True),
        ),
        migrations.AlterField(
            model_name='subscriptionaccesspolicy',
            name='group_uuid',
            field=models.UUIDField(db_index=True),
        ),
    ]
