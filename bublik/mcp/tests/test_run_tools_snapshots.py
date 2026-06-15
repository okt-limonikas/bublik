# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2025-2026 OKTET Labs Ltd. All rights reserved.

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from rest_framework.exceptions import ValidationError

from bublik.core.pagination_helpers import PaginatedResult
from bublik.core.result.services import ResultService
from bublik.data.models import ResultType
from bublik.data.models import TestIterationResult as ResultModel
from bublik.mcp import tools as mcp_tools
from bublik.mcp.run_markdown import render_run_leaf_results, render_run_overview
from bublik.mcp.tools import register_tools


if TYPE_CHECKING:
    from syrupy import SnapshotAssertion


RUN_EXAMPLES_DIR = Path(__file__).parent / 'run_examples'


@pytest.fixture
def run_stats() -> dict:
    with open(RUN_EXAMPLES_DIR / 'stats-example.json') as stats_file:
        return json.load(stats_file)


@pytest.fixture
def run_details() -> dict:
    return {
        'id': 49591,
        'project_id': 7,
        'project_name': 'DPDK',
        'start': datetime(2025, 10, 13, 0, 12, tzinfo=timezone.utc),
        'finish': datetime(2025, 10, 13, 2, 42, tzinfo=timezone.utc),
        'duration': '2:30:00',
        'main_package': 'dpdk-ethdev-ts',
        'status': 'DONE',
        'status_by_nok': 'error',
        'compromised': {
            'status': True,
            'comment': 'Infrastructure switch failed | retry required',
            'bug_id': 'BUG-42',
            'bug_url': 'https://bugs.example/BUG-42',
        },
        'conclusion': 'run-compromised',
        'conclusion_reason': 'Run marked as compromised',
        'important_tags': ['nightly', 'x86_64'],
        'relevant_tags': ['dpdk-24.11'],
        'branches': [{'name': 'main', 'value': 'main'}],
        'revisions': [{'name': 'dpdk', 'value': 'abc123'}],
        'labels': ['performance'],
        'special_categories': {'NIC': ['mlx5']},
        'configuration': {'name': 'host', 'value': 'lab-01'},
    }


@pytest.fixture
def leaf_results() -> dict:
    return {
        'leaf': {
            'result_id': 51350,
            'run_id': 49591,
            'test_name': 'vlan_filter',
            'path': ['dpdk-ethdev-ts', 'usecases', 'vlan_filter'],
        },
        'requirements': 'REQ-1;REQ-2',
        'pagination': {
            'count': 12,
            'next': 'page=2',
            'previous': None,
        },
        'results': [
            {
                'result_id': 51350,
                'exec_seqno': 1759,
                'start': datetime(2025, 10, 13, 1, 1, 44, tzinfo=timezone.utc),
                'obtained_result': {
                    'result_type': 'FAILED',
                    'verdicts': ['Packet was not received | timeout'],
                },
                'expected_results': [{'result_type': 'PASSED'}],
                'classification': 'unexpected',
                'artifacts': ['packet.pcap', 'tester.log'],
            },
            {
                'result_id': 51351,
                'exec_seqno': 1760,
                'start': datetime(2025, 10, 13, 1, 1, 46, tzinfo=timezone.utc),
                'obtained_result': {
                    'result_type': 'PASSED',
                    'verdicts': [],
                },
                'expected_results': [{'result_type': 'PASSED'}],
                'classification': 'expected',
                'artifacts': [],
            },
        ],
    }


def test_run_overview_markdown(
    run_details: dict,
    run_stats: dict,
    snapshot_md: SnapshotAssertion,
):
    output = render_run_overview(
        run_details,
        'https://logs.example/run-49591',
        run_stats,
        'REQ-1;REQ-2',
    )
    assert output == snapshot_md


def test_run_overview_unexpected_leaves_markdown(
    run_details: dict,
    run_stats: dict,
    snapshot_md: SnapshotAssertion,
):
    output = render_run_overview(
        run_details,
        'https://logs.example/run-49591',
        run_stats,
        'REQ-1;REQ-2',
        unexpected_only=True,
    )
    assert output == snapshot_md


def test_run_overview_empty_unexpected_leaves_markdown(
    run_details: dict,
    run_stats: dict,
    snapshot_md: SnapshotAssertion,
):
    stats = copy.deepcopy(run_stats)
    for node in _walk_stats(stats):
        node['stats']['passed_unexpected'] = 0
        node['stats']['failed_unexpected'] = 0
        node['stats']['skipped_unexpected'] = 0
        node['stats']['abnormal'] = 0

    output = render_run_overview(
        run_details,
        'https://logs.example/run-49591',
        stats,
        None,
        unexpected_only=True,
    )
    assert output == snapshot_md


def _walk_stats(node: dict):
    yield node
    for child in node.get('children', []):
        yield from _walk_stats(child)


def test_run_overview_includes_abnormal_only_leaf(
    run_details: dict,
    run_stats: dict,
):
    stats = copy.deepcopy(run_stats)
    leaf = next(node for node in _walk_stats(stats) if not node.get('children'))
    leaf['stats']['abnormal'] = 1

    output = render_run_overview(
        run_details,
        None,
        stats,
        None,
        unexpected_only=True,
    )

    assert f'| {leaf["result_id"]} | test |' in output


def test_run_overview_renders_comments_in_statistics_row(
    run_details: dict,
    run_stats: dict,
):
    stats = copy.deepcopy(run_stats)
    stats['comments'] = [
        {'comment': 'First | comment'},
        {'comment': 'Second comment'},
    ]

    output = render_run_overview(run_details, None, stats, None)

    root_row = next(line for line in output.splitlines() if line.startswith('| 49592 |'))
    assert 'First \\| comment<br>Second comment' in root_row
    assert '## Objectives and Comments' not in output


def test_run_leaf_results_markdown(
    leaf_results: dict,
    snapshot_md: SnapshotAssertion,
):
    assert render_run_leaf_results(leaf_results) == snapshot_md


def test_empty_run_leaf_results_markdown(
    leaf_results: dict,
    snapshot_md: SnapshotAssertion,
):
    leaf_results['pagination'] = {'count': 0, 'next': None, 'previous': None}
    leaf_results['results'] = []
    assert render_run_leaf_results(leaf_results) == snapshot_md


def _result(result_id: int, name: str, result_type: str = ResultType.TEST):
    test = SimpleNamespace(name=name, result_type=ResultType.conv(result_type))
    return SimpleNamespace(
        id=result_id,
        iteration=SimpleNamespace(test=test),
    )


def test_stats_leaf_group_contains_consecutive_same_named_tests():
    results = [
        _result(1, 'prologue'),
        _result(2, 'vlan_filter'),
        _result(3, 'vlan_filter'),
        _result(4, 'vlan_filter'),
        _result(5, 'epilogue'),
    ]

    group = ResultService._get_run_stats_leaf_group(results, 1)

    assert [result.id for result in group] == [2, 3, 4]


def test_stats_leaf_group_rejects_non_aggregate_execution():
    results = [_result(1, 'vlan_filter'), _result(2, 'vlan_filter')]

    with pytest.raises(ValidationError, match='not an aggregate leaf ID'):
        ResultService._get_run_stats_leaf_group(results, 1)


def test_paginate_queryset_counts_and_slices_querysets(
    monkeypatch: pytest.MonkeyPatch,
):
    queryset = ResultModel.objects.order_by('id')
    count_calls = []

    def count(_queryset):
        count_calls.append(True)
        return 5

    monkeypatch.setattr(type(queryset), 'count', count)

    paginated = PaginatedResult.paginate_queryset(queryset, page=2, page_size=2)

    assert count_calls == [True]
    assert paginated['pagination'] == {
        'count': 5,
        'next': 'page=3',
        'previous': 'page=1',
    }
    assert (
        paginated['results'].query.low_mark,
        paginated['results'].query.high_mark,
    ) == (2, 4)


def test_paginate_queryset_keeps_list_results_concrete():
    paginated = PaginatedResult.paginate_queryset([1, 2, 3], page=2, page_size=2)

    assert paginated['pagination'] == {
        'count': 3,
        'next': None,
        'previous': 'page=1',
    }
    assert paginated['results'] == [3]


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(function):
            self.tools[function.__name__] = function
            return function

        return decorator


def test_run_tool_registration_surface():
    mcp = FakeMCP()
    register_tools(mcp)

    assert {'get_run_overview', 'get_run_leaf_results'} <= mcp.tools.keys()
    assert {
        'get_run_details',
        'get_run_status',
        'get_run_stats',
        'get_run_source',
        'get_run_compromised',
        'list_results',
    }.isdisjoint(mcp.tools.keys())


def test_run_overview_tool_forwards_requirements(
    monkeypatch: pytest.MonkeyPatch,
    run_details: dict,
    run_stats: dict,
):
    calls = {}
    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_details',
        staticmethod(lambda run_id: run_details),
    )
    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_source',
        staticmethod(lambda run_id: 'https://logs.example/run-49591'),
    )

    def get_run_stats(run_id, requirements):
        calls['stats'] = (run_id, requirements)
        return run_stats

    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_stats',
        staticmethod(get_run_stats),
    )
    mcp = FakeMCP()
    register_tools(mcp)

    output = asyncio.run(
        mcp.tools['get_run_overview'](
            49591,
            'REQ-1;REQ-2',
            unexpected_only=True,
        ),
    )

    assert calls['stats'] == (49591, 'REQ-1;REQ-2')
    assert '| Requirements | REQ-1;REQ-2 |' in output
    assert '| Result view | unexpected leaves |' in output
    assert '| 49592 | package |' not in output


def test_run_leaf_tool_forwards_filters(
    monkeypatch: pytest.MonkeyPatch,
    leaf_results: dict,
):
    calls = {}

    def get_run_leaf_results(**kwargs):
        calls.update(kwargs)
        return leaf_results

    monkeypatch.setattr(
        mcp_tools.ResultService,
        'get_run_leaf_results',
        staticmethod(get_run_leaf_results),
    )
    mcp = FakeMCP()
    register_tools(mcp)

    asyncio.run(
        mcp.tools['get_run_leaf_results'](
            51350,
            requirements='REQ-1;REQ-2',
            results='FAILED',
            result_properties='unexpected',
            page=2,
            page_size=10,
        ),
    )

    assert calls == {
        'leaf_result_id': 51350,
        'requirements': 'REQ-1;REQ-2',
        'results': 'FAILED',
        'result_properties': 'unexpected',
        'page': 2,
        'page_size': 10,
    }
