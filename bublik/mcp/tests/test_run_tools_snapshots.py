# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2025-2026 OKTET Labs Ltd. All rights reserved.

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from pydantic import ValidationError as PydanticValidationError
import pytest
from rest_framework.exceptions import ValidationError

from bublik.core.exceptions import NotFoundError
from bublik.mcp import tools as mcp_tools
from bublik.mcp.models import RunLeafResultsPayload, RunOverviewPayload
from bublik.mcp.run_markdown import render_run_leaf_results, render_run_overview
from bublik.mcp.run_results import _get_run_leaf_results
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
        'duration': timedelta(hours=2, minutes=30),
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
        'branches': ['main: main'],
        'revisions': [
            {
                'name': 'dpdk',
                'value': 'abc123',
                'url': 'https://git.example/dpdk/commit/abc123',
            },
        ],
        'labels': ['performance'],
        'special_categories': {'NIC': ['mlx5']},
        'configuration': 'host: lab-01',
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
                'name': 'vlan_filter',
                'result_id': 51350,
                'run_id': 49591,
                'project_id': 7,
                'project_name': 'DPDK',
                'iteration_id': 9001,
                'start': datetime(2025, 10, 13, 1, 1, 44, tzinfo=timezone.utc),
                'obtained_result': {
                    'result_type': 'FAILED',
                    'verdicts': ['Packet was not received | timeout'],
                },
                'expected_results': [
                    {
                        'result_type': 'PASSED',
                        'verdicts': [],
                        'keys': [],
                    },
                ],
                'classification': 'unexpected',
                'artifacts': ['packet.pcap', 'tester.log'],
                'parameters': ['vlan: 42'],
                'comments': [],
                'requirements': ['REQ-1', 'REQ-2'],
                'has_error': True,
                'has_measurements': False,
            },
            {
                'name': 'vlan_filter',
                'result_id': 51351,
                'run_id': 49591,
                'project_id': 7,
                'project_name': 'DPDK',
                'iteration_id': 9002,
                'start': datetime(2025, 10, 13, 1, 1, 46, tzinfo=timezone.utc),
                'obtained_result': {
                    'result_type': 'PASSED',
                    'verdicts': [],
                },
                'expected_results': [
                    {
                        'result_type': 'PASSED',
                        'verdicts': [],
                        'keys': [],
                    },
                ],
                'classification': 'expected',
                'artifacts': [],
                'parameters': [],
                'comments': [],
                'requirements': ['REQ-1', 'REQ-2'],
                'has_error': False,
                'has_measurements': False,
            },
        ],
    }


def test_run_overview_markdown(
    run_details: dict,
    run_stats: dict,
    snapshot_md: SnapshotAssertion,
):
    output = render_run_overview(
        RunOverviewPayload.model_validate(
            {
                'details': run_details,
                'source': 'https://logs.example/run-49591',
                'stats': run_stats,
            },
        ),
        'REQ-1;REQ-2',
    )
    assert output == snapshot_md


def test_run_overview_unexpected_leaves_markdown(
    run_details: dict,
    run_stats: dict,
    snapshot_md: SnapshotAssertion,
):
    output = render_run_overview(
        RunOverviewPayload.model_validate(
            {
                'details': run_details,
                'source': 'https://logs.example/run-49591',
                'stats': run_stats,
            },
        ),
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
        RunOverviewPayload.model_validate(
            {
                'details': run_details,
                'source': 'https://logs.example/run-49591',
                'stats': stats,
            },
        ),
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
        RunOverviewPayload.model_validate(
            {
                'details': run_details,
                'source': None,
                'stats': stats,
            },
        ),
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
        {
            'comment_id': '1',
            'updated': '2025-10-13T01:00:00Z',
            'serial': '1',
            'comment': 'First | comment',
        },
        {
            'comment_id': '2',
            'updated': '2025-10-13T01:01:00Z',
            'serial': '2',
            'comment': 'Second comment',
        },
    ]

    payload = RunOverviewPayload.model_validate(
        {'details': run_details, 'source': None, 'stats': stats},
    )
    output = render_run_overview(payload, None)

    root_row = next(line for line in output.splitlines() if line.startswith('| 49592 |'))
    assert 'First \\| comment<br>Second comment' in root_row
    assert '## Objectives and Comments' not in output


def test_run_overview_payload_accepts_nullable_source_and_stats(run_details: dict):
    payload = RunOverviewPayload.model_validate(
        {
            'details': run_details,
            'source': None,
            'stats': None,
        },
    )

    assert payload.source is None
    assert payload.stats is None


@pytest.mark.parametrize(
    ('mutate', 'error_path'),
    [
        (lambda payload: payload.update({'extra': True}), 'extra'),
        (lambda payload: payload['details'].pop('project_id'), 'details.project_id'),
        (
            lambda payload: payload['stats']['stats'].update({'failed': -1}),
            'stats.stats.failed',
        ),
        (
            lambda payload: payload['stats'].update({'type': 'unknown'}),
            'stats.type',
        ),
        (
            lambda payload: payload['stats']['children'][0].update({'extra': True}),
            'stats.children.0.extra',
        ),
    ],
)
def test_run_overview_payload_rejects_invalid_data(
    run_details: dict,
    run_stats: dict,
    mutate,
    error_path: str,
):
    raw_payload = {
        'details': copy.deepcopy(run_details),
        'source': None,
        'stats': copy.deepcopy(run_stats),
    }
    mutate(raw_payload)

    with pytest.raises(PydanticValidationError) as error:
        RunOverviewPayload.model_validate(raw_payload)

    rendered_errors = '.'.join(str(item) for item in error.value.errors()[0]['loc'])
    assert rendered_errors == error_path


def test_run_leaf_results_markdown(
    leaf_results: dict,
    snapshot_md: SnapshotAssertion,
):
    payload = RunLeafResultsPayload.model_validate(leaf_results)
    assert render_run_leaf_results(payload) == snapshot_md


def test_empty_run_leaf_results_markdown(
    leaf_results: dict,
    snapshot_md: SnapshotAssertion,
):
    leaf_results['pagination'] = {'count': 0, 'next': None, 'previous': None}
    leaf_results['results'] = []
    payload = RunLeafResultsPayload.model_validate(leaf_results)
    assert render_run_leaf_results(payload) == snapshot_md


@pytest.mark.parametrize(
    ('mutate', 'error_path'),
    [
        (lambda payload: payload.update({'extra': True}), 'extra'),
        (lambda payload: payload['pagination'].update({'count': -1}), 'pagination.count'),
        (
            lambda payload: payload['results'][0].update({'classification': 'unknown'}),
            'results.0.classification',
        ),
        (
            lambda payload: payload['results'][0]['obtained_result'].update(
                {'extra': True},
            ),
            'results.0.obtained_result.extra',
        ),
        (
            lambda payload: payload['results'][0].pop('project_id'),
            'results.0.project_id',
        ),
    ],
)
def test_run_leaf_payload_rejects_invalid_data(
    leaf_results: dict,
    mutate,
    error_path: str,
):
    raw_payload = copy.deepcopy(leaf_results)
    mutate(raw_payload)

    with pytest.raises(PydanticValidationError) as error:
        RunLeafResultsPayload.model_validate(raw_payload)

    rendered_errors = '.'.join(str(item) for item in error.value.errors()[0]['loc'])
    assert rendered_errors == error_path


def _stats_node(
    result_id: int = 51350,
    node_type: str = 'test',
    children: list[dict] | None = None,
) -> dict:
    return {
        'result_id': result_id,
        'exec_seqno': 1759,
        'parent_id': 49594,
        'type': node_type,
        'test_id': 261,
        'test_name': 'vlan_filter',
        'period': '1760307704s792-1760307725s503',
        'path': ['dpdk-ethdev-ts', 'usecases', 'vlan_filter'],
        'objective': '',
        'children': children or [],
        'stats': {
            'passed': 0,
            'failed': 0,
            'passed_unexpected': 0,
            'failed_unexpected': 12,
            'skipped': 0,
            'skipped_unexpected': 0,
            'abnormal': 0,
        },
        'comments': [],
    }


def _service_results(leaf_results: dict) -> dict:
    rows = copy.deepcopy(leaf_results['results'])
    for row in rows:
        row.pop('classification')
    return {
        'pagination': copy.deepcopy(leaf_results['pagination']),
        'results': rows,
    }


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


def test_run_overview_tool_validates_before_rendering(
    monkeypatch: pytest.MonkeyPatch,
    run_details: dict,
    run_stats: dict,
):
    malformed_details = {**run_details, 'unexpected_field': True}
    renderer_called = False

    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_details',
        staticmethod(lambda run_id: malformed_details),
    )
    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_source',
        staticmethod(lambda run_id: None),
    )
    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_stats',
        staticmethod(lambda run_id, requirements: run_stats),
    )

    def render(*args, **kwargs):
        nonlocal renderer_called
        renderer_called = True
        return ''

    monkeypatch.setattr(mcp_tools, 'render_run_overview', render)
    mcp = FakeMCP()
    register_tools(mcp)

    with pytest.raises(PydanticValidationError, match='unexpected_field'):
        asyncio.run(mcp.tools['get_run_overview'](49591))

    assert not renderer_called


def test_run_leaf_tool_forwards_filters(
    monkeypatch: pytest.MonkeyPatch,
    leaf_results: dict,
):
    calls = {}
    monkeypatch.setattr(
        mcp_tools.ResultService,
        'get_result',
        staticmethod(lambda result_id: SimpleNamespace(test_run_id=49591)),
    )

    def get_run_stats(run_id, requirements):
        calls['stats'] = (run_id, requirements)
        return _stats_node()

    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_stats',
        staticmethod(get_run_stats),
    )

    def list_results_paginated(**kwargs):
        calls['results'] = kwargs
        return _service_results(leaf_results)

    monkeypatch.setattr(
        mcp_tools.ResultService,
        'list_results_paginated',
        staticmethod(list_results_paginated),
    )
    mcp = FakeMCP()
    register_tools(mcp)

    output = asyncio.run(
        mcp.tools['get_run_leaf_results'](
            51350,
            requirements='REQ-1;REQ-2',
            results='FAILED',
            result_properties='unexpected',
            page=2,
            page_size=10,
        ),
    )

    assert calls['stats'] == (49591, None)
    assert calls['results'] == {
        'parent_id': 49594,
        'test_name': 'vlan_filter',
        'start_exec_seqno': 1759,
        'requirements': 'REQ-1;REQ-2',
        'results': 'FAILED',
        'result_properties': 'unexpected',
        'page': 2,
        'page_size': 10,
    }
    assert '| unexpected |' in output
    assert '| expected |' in output


def test_run_leaf_tool_validates_before_rendering(
    monkeypatch: pytest.MonkeyPatch,
    leaf_results: dict,
):
    malformed_results = _service_results(leaf_results)
    malformed_results['results'][0]['extra'] = True
    renderer_called = False

    monkeypatch.setattr(
        mcp_tools.ResultService,
        'get_result',
        staticmethod(lambda result_id: SimpleNamespace(test_run_id=49591)),
    )
    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_stats',
        staticmethod(lambda run_id, requirements: _stats_node()),
    )
    monkeypatch.setattr(
        mcp_tools.ResultService,
        'list_results_paginated',
        staticmethod(lambda **kwargs: malformed_results),
    )

    def render(*args, **kwargs):
        nonlocal renderer_called
        renderer_called = True
        return ''

    monkeypatch.setattr(mcp_tools, 'render_run_leaf_results', render)
    mcp = FakeMCP()
    register_tools(mcp)

    with pytest.raises(PydanticValidationError, match='extra'):
        asyncio.run(mcp.tools['get_run_leaf_results'](51350))

    assert not renderer_called


@pytest.mark.parametrize('node_type', ['pkg', 'session'])
def test_run_leaf_adapter_rejects_package_and_session_nodes(
    monkeypatch: pytest.MonkeyPatch,
    node_type: str,
):
    monkeypatch.setattr(
        mcp_tools.ResultService,
        'get_result',
        staticmethod(lambda result_id: SimpleNamespace(test_run_id=49591)),
    )
    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_stats',
        staticmethod(lambda run_id, requirements: _stats_node(node_type=node_type)),
    )

    with pytest.raises(ValidationError, match='test leaf result ID'):
        _get_run_leaf_results(51350)


def test_run_leaf_adapter_rejects_unknown_result_id(
    monkeypatch: pytest.MonkeyPatch,
):
    def get_result(result_id):
        msg = f'Result {result_id} not found'
        raise NotFoundError(msg)

    monkeypatch.setattr(
        mcp_tools.ResultService,
        'get_result',
        staticmethod(get_result),
    )

    with pytest.raises(NotFoundError, match='Result 99999 not found'):
        _get_run_leaf_results(99999)


def test_run_leaf_adapter_rejects_non_aggregate_execution(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        mcp_tools.ResultService,
        'get_result',
        staticmethod(lambda result_id: SimpleNamespace(test_run_id=49591)),
    )
    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_stats',
        staticmethod(lambda run_id, requirements: _stats_node()),
    )

    with pytest.raises(ValidationError, match='not an aggregate leaf ID'):
        _get_run_leaf_results(51351)


def test_run_leaf_adapter_rejects_unavailable_stats(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        mcp_tools.ResultService,
        'get_result',
        staticmethod(lambda result_id: SimpleNamespace(test_run_id=49591)),
    )
    monkeypatch.setattr(
        mcp_tools.RunService,
        'get_run_stats',
        staticmethod(lambda run_id, requirements: None),
    )

    with pytest.raises(ValidationError, match='unavailable for run 49591'):
        _get_run_leaf_results(51350)
