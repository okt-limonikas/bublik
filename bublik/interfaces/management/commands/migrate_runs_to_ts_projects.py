# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2025 OKTET Labs Ltd. All rights reserved.


from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand
from django.db import transaction

from bublik.core.shortcuts import serialize
from bublik.data.models import (
    Config,
    Meta,
    MetaResult,
)
from bublik.data.serializers import (
    ConfigSerializer,
    MetaSerializer,
)


class Command(BaseCommand):

    def handle(self, *args, **options):
        self.stdout.write('Migrating runs to projects based on associated test suites:')

        projects = Meta.objects.filter(type='label', name='PROJECT')
        test_suites = Meta.objects.filter(
            type='label',
            name='TS_NAME',
            metaresult__isnull=False,
        )

        project_names = set(projects.values_list('value', flat=True))
        ts_names = set(test_suites.values_list('value', flat=True))
        if set(ts_names).issubset(project_names):
            self.stdout.write('Already migrated.')
            return

        with transaction.atomic():
            for project in projects:
                self.stdout.write(f'Processing project \'{project.value}\'...')

                self.stdout.write(
                    '\tCreating new projects based on test suite names and configurations...',
                )

                project_ts_names = list(
                    Meta.objects.filter(
                        name='TS_NAME',
                        metaresult__result__meta_results__meta=project,
                    )
                    .distinct()
                    .values_list('value', flat=True),
                )
                self.stdout.write(f'\tNew project names: {project_ts_names}')

                project_configs = Config.objects.filter(project=project, is_active=True)

                for new_project_name in project_ts_names:
                    m_data = {'name': 'PROJECT', 'type': 'label', 'value': new_project_name}
                    meta_serializer = serialize(MetaSerializer, m_data)
                    new_project, created = meta_serializer.get_or_create()

                    if created:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'\tSuccessfully created project: {new_project_name}',
                            ),
                        )
                        for project_config in project_configs:
                            ConfigSerializer.initialize(
                                {
                                    'type': project_config.type,
                                    'name': project_config.name,
                                    'project': new_project,
                                    'description': project_config.description,
                                    'content': project_config.content,
                                },
                            )
                        self.stdout.write(
                            self.style.SUCCESS(
                                '\tConfigs successfully initialized for project: '
                                f'{new_project_name}',
                            ),
                        )
                    else:
                        self.stdout.write(
                            f'\tThe project already exists: {new_project_name}. '
                            'Configs initialization skipped.',
                        )

                self.stdout.write(
                    self.style.SUCCESS(
                        'New projects and corresponding configs were successfully created',
                    ),
                )

            self.stdout.write('Deleting all existing run-to-project associations...')
            MetaResult.objects.filter(meta__type='label', meta__name='PROJECT').delete()

            self.stdout.write('Creating run-to-project associations for new projects...')

            run_to_ts = dict(
                MetaResult.objects.filter(meta__name='TS_NAME', meta__type='label').values_list(
                    'result_id',
                    'meta__value',
                ),
            )

            project_metas = Meta.objects.filter(name='PROJECT', type='label')
            project_name_to_meta = {m.value: m for m in project_metas}

            metaresults_to_create = []
            for run_id, ts in run_to_ts.items():
                project_meta = project_name_to_meta.get(ts)
                if project_meta:
                    metaresults_to_create.append(
                        MetaResult(meta=project_meta, result_id=run_id),
                    )
                else:
                    msg = f'No matching \'PROJECT\' meta for value=\'{ts}\''
                    raise ObjectDoesNotExist(msg)

            MetaResult.objects.bulk_create(metaresults_to_create, ignore_conflicts=True)
            self.stdout.write(
                self.style.SUCCESS('Run-to-project associations successfully created!'),
            )
