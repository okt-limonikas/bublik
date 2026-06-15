# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2025-2026 OKTET Labs Ltd. All rights reserved.

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from bublik.core.exceptions import NotFoundError
from bublik.core.measurement.services import (
    get_measurement_charts,
    get_measurement_results,
)
from bublik.core.pagination_helpers import PaginatedResult
from bublik.core.queries import get_or_none
from bublik.core.run.stats import (
    generate_result_details,
    generate_results_details,
)
from bublik.core.run.tests_organization import get_test_ids_by_name
from bublik.core.utils import get_difference
from bublik.data import models


class ResultService:
    @staticmethod
    def get_result(result_id: int) -> models.TestIterationResult:
        '''
        Get a result by ID.

        Args:
            result_id: The ID of the test result

        Returns:
            TestIterationResult instance

        Raises:
            NotFoundError: if result not found
        '''
        try:
            return models.TestIterationResult.objects.get(id=result_id)
        except ObjectDoesNotExist as e:
            msg = f'Result {result_id} not found'
            raise NotFoundError(msg) from e

    @staticmethod
    def get_result_details(result_id: int) -> dict:
        '''
        Get full details for a single result.

        Args:
            result_id: The ID of the test result

        Returns:
            Dictionary with full result details
        '''

        result = ResultService.get_result(result_id)

        return generate_result_details(result)

    @staticmethod
    def get_result_measurements(result_id: int) -> dict:
        '''
        Get measurements for a result.

        Args:
            result_id: The ID of the test result

        Returns:
            Dictionary with run_id, iteration_id, charts, and tables
        '''
        result = ResultService.get_result(result_id)

        # Get tables
        mmrs = get_measurement_results([result_id])
        tables = [mmr.representation(additional='measurement') for mmr in mmrs]

        return {
            'run_id': result.test_run_id,
            'iteration_id': result.iteration_id,
            'charts': get_measurement_charts(result_id),
            'tables': tables,
        }

    @staticmethod
    def get_result_artifacts_and_verdicts(result_id: int) -> dict:
        '''
        Get artifacts and verdicts for a result.

        Args:
            result_id: The ID of the test result

        Returns:
            Dictionary with artifacts and verdicts lists
        '''
        result_metas = models.Meta.objects.filter(metaresult__result__id=result_id)
        return {
            'artifacts': list(result_metas.filter(type='artifact').values()),
            'verdicts': list(result_metas.filter(type='verdict').values()),
        }

    @staticmethod
    def list_results(
        parent_id: int | None = None,
        test_name: str | None = None,
        start_exec_seqno: str | None = None,
        results: str | None = None,
        result_properties: str | None = None,
        requirements: str | None = None,
    ):
        '''
        List results with filtering.

        Args:
            parent_id: Filter by parent package ID
            test_name: Filter by test name
            start_exec_seqno: Retain only the consecutive sequence of results
                starting from the specified execution number, based on the global
                run sequence
            results: Comma-separated result statuses
            result_properties: Comma-separated result properties
            requirements: Comma-separated requirement names

        Returns:
            QuerySet of filtered TestIterationResult objects

        Raises:
            ValidationError: if validation fails
        '''
        queries = Q()
        queryset = models.TestIterationResult.objects.filter()
        query_delimiter = settings.QUERY_DELIMITER
        errors = []

        # parent_id filtering
        if parent_id:
            parent_obj = get_or_none(models.TestIterationResult.objects, id=parent_id)
            if not parent_obj:
                errors.append('No test iteration result found by the given parent id')
            queries &= Q(parent_package=parent_id)

        # test_name filtering
        if test_name:
            test_ids = get_test_ids_by_name(test_name)
            if not test_ids:
                errors.append('No tests found by the given test name')
            queries &= Q(iteration__test__in=test_ids, iteration__hash__isnull=False)

        if errors:
            raise ValidationError(errors)

        queryset = queryset.filter(queries)

        # Retain only results consecutive relative to the global run sequence,
        # starting from the specified execution number.
        # A gap is detected when a foreign exec_seqno (belonging to a different test)
        # appears between two local ones.
        if start_exec_seqno:
            start_exec_seqno = int(start_exec_seqno)

            local_seqnos = queryset.values('exec_seqno').distinct()

            first_foreign = (
                models.TestIterationResult.objects.filter(
                    test_run=parent_obj.test_run,
                    exec_seqno__gte=start_exec_seqno,
                )
                .exclude(exec_seqno__in=local_seqnos)
                .order_by('exec_seqno')
                .values('exec_seqno')
                .first()
            )

            queryset = queryset.filter(exec_seqno__gte=start_exec_seqno)
            if first_foreign is not None:
                queryset = queryset.filter(exec_seqno__lt=first_foreign['exec_seqno'])

        # results/status filtering
        if results:
            results_list = results.split(query_delimiter)
            diff = get_difference(results_list, models.ResultStatus.all_statuses())
            if diff:
                errors.append(f'Unknown result results: {diff}')
            queryset = queryset.filter(
                meta_results__meta__type='result',
                meta_results__meta__value__in=results_list,
            )

        if errors:
            raise ValidationError(errors)

        # result_properties filtering
        if result_properties:
            queryset = queryset.filter_by_result_classification(
                result_properties.split(query_delimiter),
            )

        # requirements filtering
        if requirements:
            requirements_list = requirements.split(query_delimiter)
            available_req_metas = []
            for requirement in requirements_list:
                try:
                    available_req_metas.append(
                        models.Meta.objects.get(type='requirement', value=requirement),
                    )
                except ObjectDoesNotExist:
                    return models.TestIterationResult.objects.none()
            for req_meta in available_req_metas:
                queryset = queryset.filter(meta_results__meta=req_meta)

        return (
            queryset.order_by('-start', 'id')
            .select_related('iteration', 'project')
            .prefetch_related(
                'expectations',
                'expectations__expectmeta_set',
                'measurement_results',
                'meta_results__meta',
                'iteration__test_arguments',
            )
            .distinct('id', 'start')
        )

    @staticmethod
    def list_results_paginated(
        parent_id: int | None = None,
        test_name: str | None = None,
        start_exec_seqno: str | None = None,
        results: str | None = None,
        result_properties: str | None = None,
        requirements: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict:
        '''
        List results with filtering and pagination.

        Args:
            parent_id: Filter by parent package ID
            test_name: Filter by test name
            start_exec_seqno: Retain only the consecutive sequence of results
                starting from the specified execution number, based on the global
                run sequence
            results: Comma-separated result statuses
            result_properties: Comma-separated result properties
            requirements: Comma-separated requirement names
            page: Page number (default: 1)
            page_size: Items per page (default: 25, max: 10000)

        Returns:
            Dictionary with pagination metadata and result details
        '''
        queryset = ResultService.list_results(
            parent_id=parent_id,
            test_name=test_name,
            start_exec_seqno=start_exec_seqno,
            results=results,
            result_properties=result_properties,
            requirements=requirements,
        )

        results_details = generate_results_details(queryset)
        return PaginatedResult.paginate_queryset(results_details, page, page_size)

    @staticmethod
    def get_run_leaf_results(
        leaf_result_id: int,
        requirements: str | None = None,
        results: str | None = None,
        result_properties: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict:
        '''
        Return concrete executions represented by an aggregate run-stats leaf.

        A stats leaf points at the first result in a consecutive sequence of
        same-named test executions under one parent package. This method uses
        the same grouping rule as run statistics and then applies optional
        filters to the concrete executions.
        '''
        leaf = (
            models.TestIterationResult.objects.select_related(
                'iteration__test',
                'parent_package',
                'test_run',
            )
            .filter(id=leaf_result_id)
            .first()
        )
        if leaf is None:
            msg = f'Result {leaf_result_id} not found'
            raise NotFoundError(msg)

        if (
            leaf.test_run_id is None
            or leaf.iteration is None
            or models.ResultType.inv(leaf.iteration.test.result_type)
            != models.ResultType.TEST
        ):
            msg = 'A test leaf result ID from get_run_overview is required'
            raise ValidationError(msg)

        siblings = list(
            models.TestIterationResult.objects.filter(
                test_run_id=leaf.test_run_id,
                parent_package_id=leaf.parent_package_id,
            )
            .select_related('iteration__test')
            .order_by('start'),
        )
        leaf_index = next(
            (index for index, sibling in enumerate(siblings) if sibling.id == leaf.id),
            None,
        )
        if leaf_index is None:
            msg = 'The requested result is not part of its run result tree'
            raise ValidationError(msg)

        test_name = leaf.iteration.test.name
        group = ResultService._get_run_stats_leaf_group(siblings, leaf_index)
        group_ids = [result.id for result in group]
        queryset = models.TestIterationResult.objects.filter(id__in=group_ids)
        query_delimiter = settings.QUERY_DELIMITER
        errors = []

        if results:
            results_list = results.split(query_delimiter)
            diff = get_difference(results_list, models.ResultStatus.all_statuses())
            if diff:
                errors.append(f'Unknown result results: {diff}')
            queryset = queryset.filter(
                meta_results__meta__type='result',
                meta_results__meta__value__in=results_list,
            )

        if errors:
            raise ValidationError(errors)

        if result_properties:
            queryset = queryset.filter_by_result_classification(
                result_properties.split(query_delimiter),
            )

        if requirements:
            for requirement in requirements.split(query_delimiter):
                requirement_meta = models.Meta.objects.filter(
                    type='requirement',
                    value=requirement,
                ).first()
                if requirement_meta is None:
                    queryset = models.TestIterationResult.objects.none()
                    break
                queryset = queryset.filter(meta_results__meta=requirement_meta)

        queryset = (
            queryset.order_by('start', 'id')
            .select_related('iteration', 'iteration__test', 'project')
            .prefetch_related(
                'expectations',
                'expectations__expectmeta_set',
                'measurement_results',
                'meta_results__meta',
                'iteration__test_arguments',
            )
            .distinct()
        )
        paginated = PaginatedResult.paginate_queryset(queryset, page, page_size)
        concrete_results = list(paginated['results'])
        details_by_id = {
            detail['result_id']: detail
            for detail in generate_results_details(concrete_results)
        }
        result_rows = []
        for result in concrete_results:
            detail = details_by_id[result.id]
            detail['exec_seqno'] = result.exec_seqno
            detail['classification'] = (
                'unexpected' if detail['has_error'] else 'expected'
            )
            result_rows.append(detail)

        paginated['results'] = result_rows
        return {
            'leaf': {
                'result_id': leaf.id,
                'run_id': leaf.test_run_id,
                'test_name': test_name,
                'path': ResultService._get_result_path(leaf),
            },
            'requirements': requirements,
            **paginated,
        }

    @staticmethod
    def _get_result_path(result: models.TestIterationResult) -> list[str]:
        path = [result.iteration.test.name]
        parent = result.parent_package
        while parent is not None:
            path.append(parent.iteration.test.name)
            parent = parent.parent_package
        return list(reversed(path))

    @staticmethod
    def _get_run_stats_leaf_group(results: list, leaf_index: int) -> list:
        leaf = results[leaf_index]
        test_name = leaf.iteration.test.name
        group_start = leaf_index
        while (
            group_start > 0
            and results[group_start - 1].iteration.test.name == test_name
            and models.ResultType.inv(
                results[group_start - 1].iteration.test.result_type,
            )
            == models.ResultType.TEST
        ):
            group_start -= 1

        if group_start != leaf_index:
            msg = (
                'Result ID is not an aggregate leaf ID; use the leaf result ID '
                'shown by get_run_overview'
            )
            raise ValidationError(msg)

        group_end = leaf_index + 1
        while (
            group_end < len(results)
            and results[group_end].iteration.test.name == test_name
            and models.ResultType.inv(results[group_end].iteration.test.result_type)
            == models.ResultType.TEST
        ):
            group_end += 1

        return results[group_start:group_end]
