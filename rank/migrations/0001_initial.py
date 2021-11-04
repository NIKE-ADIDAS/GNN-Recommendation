# Generated by Django 3.2.8 on 2021-11-03 13:45

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Author',
            fields=[
                ('id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('name', models.CharField(db_index=True, max_length=255)),
                ('n_citation', models.IntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='Field',
            fields=[
                ('id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='Institution',
            fields=[
                ('id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('name', models.CharField(db_index=True, max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='Paper',
            fields=[
                ('id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('title', models.CharField(db_index=True, max_length=255)),
                ('year', models.IntegerField()),
                ('abstract', models.CharField(max_length=4095)),
                ('n_citation', models.IntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='Venue',
            fields=[
                ('id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('name', models.CharField(db_index=True, max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='Writes',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.IntegerField(default=1)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='rank.author')),
                ('paper', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='rank.paper')),
            ],
        ),
        migrations.AddField(
            model_name='paper',
            name='authors',
            field=models.ManyToManyField(related_name='papers', through='rank.Writes', to='rank.Author'),
        ),
        migrations.AddField(
            model_name='paper',
            name='fos',
            field=models.ManyToManyField(to='rank.Field'),
        ),
        migrations.AddField(
            model_name='paper',
            name='references',
            field=models.ManyToManyField(related_name='citations', to='rank.Paper'),
        ),
        migrations.AddField(
            model_name='paper',
            name='venue',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='rank.venue'),
        ),
        migrations.AddField(
            model_name='author',
            name='institution',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='rank.institution'),
        ),
        migrations.AddConstraint(
            model_name='writes',
            constraint=models.UniqueConstraint(fields=('author', 'paper'), name='unique_writes'),
        ),
    ]
