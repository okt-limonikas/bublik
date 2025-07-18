# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2025 OKTET Labs Ltd. All rights reserved.


from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, OuterRef, Subquery

from bublik.core.shortcuts import serialize
from bublik.data.models import (
    Config,
    Meta,
    MetaResult,
    TestIterationResult,
)
from bublik.data.serializers import (
    ConfigSerializer,
    MetaSerializer,
)


class Command(BaseCommand):

    def handle(self, *args, **options):
        self.stdout.write('Migrating runs to projects based on associated test suites:')

        # Check whether there are runs associated with projects that do not match any TS names
        ts_name_value = Meta.objects.filter(
            metaresult__result=OuterRef('pk'),
            name='TS_NAME',
            type='label',
        ).values('value')[:1]
        project_value = Meta.objects.filter(
            metaresult__result=OuterRef('pk'),
            name='PROJECT',
            type='label',
        ).values('value')[:1]
        runs_to_migrate = TestIterationResult.objects.annotate(
            ts_value=Subquery(ts_name_value),
            project_value=Subquery(project_value),
        ).exclude(ts_value=F('project_value'))
        if not runs_to_migrate.exists():
            self.stdout.write('Already migrated.')
            return

        test_suites_with_runs = Meta.objects.filter(
            type='label',
            name='TS_NAME',
            metaresult__isnull=False,
        ).distinct()
        test_suite_with_runs_names = list(test_suites_with_runs.values_list('value', flat=True))
        self.stdout.write(
            f'Test suites: {test_suite_with_runs_names}',
        )
        for ts in test_suites_with_runs:
            with transaction.atomic():
                self.stdout.write(f'Processing {ts.value} test suite:')

                ts_runs_to_migrate = runs_to_migrate.filter(
                    meta_results__meta__type='label',
                    meta_results__meta__name='TS_NAME',
                    meta_results__meta__value=ts.value,
                )
                if not ts_runs_to_migrate.exists():
                    self.stdout.write('\tRuns already migrated.')
                    continue

                ts_runs_to_migrate_ids = list(ts_runs_to_migrate.values_list('id', flat=True))

                try:
                    project_meta = Meta.projects.get(value=ts.value)
                    self.stdout.write(f'\tProject {ts.value} already exist.')
                except ObjectDoesNotExist:
                    # Create project
                    self.stdout.write('\tCreating new project and configurations...')
                    m_data = {'name': 'PROJECT', 'type': 'label', 'value': ts.value}
                    meta_serializer = serialize(MetaSerializer, m_data)
                    project_meta, _ = meta_serializer.get_or_create()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'\tProject {ts.value} successfully created!',
                        ),
                    )

                    # Check that all runs with this TS_NAME belong to the same project
                    ts_project_names = list(
                        Meta.projects.filter(
                            metaresult__result_id__in=ts_runs_to_migrate_ids,
                        )
                        .values_list('value', flat=True)
                        .distinct(),
                    )
                    if len(ts_project_names) > 1:
                        self.stdout.write(
                            self.style.WARNING(
                                f'\tRuns with TS_NAME \'{ts.value}\' are associated with '
                                f'multiple projects: {ts_project_names}. '
                                'Skipping configuration creation due to ambiguity.',
                            ),
                        )
                    else:
                        # Initialize configs for new project
                        project_configs = Config.objects.filter(
                            project__value=ts_project_names[0],
                            is_active=True,
                        )
                        for project_config in project_configs:
                            ConfigSerializer.initialize(
                                {
                                    'type': project_config.type,
                                    'name': project_config.name,
                                    'project': project_meta,
                                    'description': project_config.description,
                                    'content': project_config.content,
                                },
                            )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'\tConfigs for {ts.value} successfully initialized!',
                            ),
                        )
                finally:
                    # Migrate runs
                    self.stdout.write('\tMigrating runs:')
                    self.stdout.write(
                        f'\tThe number of runs to migrate: {len(ts_runs_to_migrate_ids)}',
                    )
                    metaresults_to_create = []
                    for run_id in ts_runs_to_migrate_ids:
                        metaresults_to_create.append(
                            MetaResult(meta=project_meta, result_id=run_id),
                        )
                    self.stdout.write('\tDeleting existing run-to-project associations...')
                    MetaResult.objects.filter(
                        result_id__in=ts_runs_to_migrate_ids,
                        meta__type='label',
                        meta__name='PROJECT',
                    ).delete()
                    self.stdout.write('\tCreating new run-to-project associations...')
                    MetaResult.objects.bulk_create(metaresults_to_create, ignore_conflicts=True)
                    self.stdout.write(self.style.SUCCESS('\tRuns successfully migrated!'))
