# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2025-2026 OKTET Labs Ltd. All rights reserved.

from __future__ import annotations

import json
from typing import Any


def _cell(value: Any) -> str:
    if value is None or value == '' or (
        isinstance(value, (dict, list, tuple)) and not value
    ):
        return '-'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, default=str, ensure_ascii=True, sort_keys=True)
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def _flatten_stats(node: dict | None) -> list[dict]:
    if not node:
        return []
    descendants = (
        item
        for child in node.get('children', [])
        for item in _flatten_stats(child)
    )
    return [node, *descendants]


def render_run_overview(
    details: dict,
    source: str | None,
    stats: dict | None,
    requirements: str | None,
) -> str:
    compromised = details.get('compromised') or {'status': False}
    rows = [
        ('Run ID', details.get('id')),
        ('Project', details.get('project_name')),
        ('Status', details.get('status')),
        ('Status by NOK', details.get('status_by_nok')),
        ('Conclusion', details.get('conclusion')),
        ('Conclusion reason', details.get('conclusion_reason')),
        ('Start', details.get('start')),
        ('Finish', details.get('finish')),
        ('Duration', details.get('duration')),
        ('Main package', details.get('main_package')),
        ('Source', source),
        ('Requirements', requirements or 'none'),
        ('Compromised', compromised.get('status', False)),
        ('Compromised comment', compromised.get('comment')),
        ('Compromised bug', compromised.get('bug_url') or compromised.get('bug_id')),
        ('Important tags', details.get('important_tags')),
        ('Relevant tags', details.get('relevant_tags')),
        ('Branches', details.get('branches')),
        ('Revisions', details.get('revisions')),
        ('Labels', details.get('labels')),
        ('Configuration', details.get('configuration')),
        ('Special categories', details.get('special_categories')),
    ]
    lines = [
        f'# Run {_cell(details.get("id"))} Overview',
        '',
        '| Field | Value |',
        '|---|---|',
        *(f'| {_cell(name)} | {_cell(value)} |' for name, value in rows),
        '',
        '## Result Statistics',
        '',
        (
            '| Result ID | Type | Path | Passed | Failed | Passed NOK | Failed NOK | '
            'Skipped | Skipped NOK | Abnormal | Total | NOK |'
        ),
        '|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]

    stat_nodes = _flatten_stats(stats)
    for node in stat_nodes:
        node_stats = node.get('stats', {})
        total = sum(node_stats.values())
        nok = sum(
            node_stats.get(name, 0)
            for name in (
                'passed_unexpected',
                'failed_unexpected',
                'skipped_unexpected',
                'abnormal',
            )
        )
        result_type = {'pkg': 'package', 'session': 'session', 'test': 'test'}.get(
            node.get('type'),
            node.get('type'),
        )
        lines.append(
            '| {result_id} | {result_type} | {path} | {passed} | {failed} | '
            '{passed_nok} | {failed_nok} | {skipped} | {skipped_nok} | '
            '{abnormal} | {total} | {nok} |'.format(
                result_id=_cell(node.get('result_id')),
                result_type=_cell(result_type),
                path=_cell(' / '.join(node.get('path', []))),
                passed=node_stats.get('passed', 0),
                failed=node_stats.get('failed', 0),
                passed_nok=node_stats.get('passed_unexpected', 0),
                failed_nok=node_stats.get('failed_unexpected', 0),
                skipped=node_stats.get('skipped', 0),
                skipped_nok=node_stats.get('skipped_unexpected', 0),
                abnormal=node_stats.get('abnormal', 0),
                total=total,
                nok=nok,
            ),
        )

    if not stat_nodes:
        lines.append('| - | - | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |')

    annotations = [
        node
        for node in stat_nodes
        if node.get('objective') or node.get('comments')
    ]
    if annotations:
        lines.extend(
            [
                '',
                '## Objectives and Comments',
                '',
                '| Result ID | Path | Objective | Comments |',
                '|---:|---|---|---|',
            ],
        )
        for node in annotations:
            comments = [
                comment.get('comment', comment) if isinstance(comment, dict) else comment
                for comment in node.get('comments', [])
            ]
            lines.append(
                f'| {_cell(node.get("result_id"))} | '
                f'{_cell(" / ".join(node.get("path", [])))} | '
                f'{_cell(node.get("objective"))} | {_cell(comments)} |',
            )

    lines.extend(
        [
            '',
            '*Use a test row Result ID with `get_run_leaf_results` to inspect '
            'its concrete executions.*',
        ],
    )
    return '\n'.join(lines)


def _expected_result_text(expected_results: list[dict]) -> str:
    values = [item.get('result_type') for item in expected_results if item.get('result_type')]
    return ', '.join(values) if values else '-'


def render_run_leaf_results(data: dict) -> str:
    leaf = data['leaf']
    pagination = data['pagination']
    lines = [
        f'# Leaf Results: {_cell(leaf.get("test_name"))}',
        '',
        f'Path: `{_cell(" / ".join(leaf.get("path", [])))}`',
        f'Aggregate leaf: `{_cell(leaf.get("result_id"))}`',
        f'Run: `{_cell(leaf.get("run_id"))}`',
        f'Requirements: `{_cell(data.get("requirements") or "none")}`',
        '',
        (
            '| Result ID | Exec Seqno | Start | Obtained | Expected | Classification | '
            'Verdicts | Artifacts |'
        ),
        '|---:|---:|---|---|---|---|---|---:|',
    ]
    for result in data['results']:
        obtained = result.get('obtained_result') or {}
        lines.append(
            f'| {_cell(result.get("result_id"))} | {_cell(result.get("exec_seqno"))} | '
            f'{_cell(result.get("start"))} | {_cell(obtained.get("result_type"))} | '
            f'{_cell(_expected_result_text(result.get("expected_results", [])))} | '
            f'{_cell(result.get("classification"))} | '
            f'{_cell(obtained.get("verdicts", []))} | '
            f'{len(result.get("artifacts", []))} |',
        )
    if not data['results']:
        lines.append('| - | - | - | - | - | - | - | 0 |')

    page = 1
    if pagination.get('previous'):
        page = int(pagination['previous'].split('=')[1]) + 1
    lines.extend(
        [
            '',
            (
                f'*Page {page} | {pagination["count"]} results | '
                f'previous: {pagination.get("previous") or "-"} | '
                f'next: {pagination.get("next") or "-"}*'
            ),
        ],
    )
    return '\n'.join(lines)
