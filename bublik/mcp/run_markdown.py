# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2025-2026 OKTET Labs Ltd. All rights reserved.

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel


if TYPE_CHECKING:
    from bublik.mcp.models import (
        RunLeafResultsPayload,
        RunOverviewPayload,
        RunStatsComment,
        RunStatsNode,
    )


def _cell(value: Any) -> str:
    if value is None or value == '' or (
        isinstance(value, (dict, list, tuple)) and not value
    ):
        return '-'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json')
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(
            value,
            default=lambda item: (
                item.model_dump(mode='json') if isinstance(item, BaseModel) else str(item)
            ),
            ensure_ascii=True,
            sort_keys=True,
        )
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def _flatten_stats(node: RunStatsNode | None) -> list[RunStatsNode]:
    if not node:
        return []
    descendants = (
        item
        for child in node.children
        for item in _flatten_stats(child)
    )
    return [node, *descendants]


def _comments_text(comments: list[RunStatsComment]) -> str:
    values = [comment.comment for comment in comments]
    return '<br>'.join(str(value) for value in values) if values else '-'


def render_run_overview(
    payload: RunOverviewPayload,
    requirements: str | None,
    unexpected_only: bool = False,
) -> str:
    details = payload.details
    compromised = details.compromised
    rows = [
        ('Run ID', details.id),
        ('Project', details.project_name),
        ('Status', details.status),
        ('Status by NOK', details.status_by_nok),
        ('Conclusion', details.conclusion),
        ('Conclusion reason', details.conclusion_reason),
        ('Start', details.start),
        ('Finish', details.finish),
        ('Duration', details.duration),
        ('Main package', details.main_package),
        ('Source', payload.source),
        ('Requirements', requirements or 'none'),
        ('Result view', 'unexpected leaves' if unexpected_only else 'all results'),
        ('Compromised', compromised.status),
        ('Compromised comment', compromised.comment),
        ('Compromised bug', compromised.bug_url or compromised.bug_id),
        ('Important tags', details.important_tags),
        ('Relevant tags', details.relevant_tags),
        ('Branches', details.branches),
        ('Revisions', details.revisions),
        ('Labels', details.labels),
        ('Configuration', details.configuration),
        ('Special categories', details.special_categories),
    ]
    lines = [
        f'# Run {_cell(details.id)} Overview',
        '',
        '| Field | Value |',
        '|---|---|',
        *(f'| {_cell(name)} | {_cell(value)} |' for name, value in rows),
        '',
        '## Result Statistics',
        '',
        (
            '| Result ID | Type | Path | Objective | Comments | Passed | Failed | '
            'Passed NOK | Failed NOK | Skipped | Skipped NOK | Abnormal | Total | NOK |'
        ),
        '|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]

    stat_nodes = _flatten_stats(payload.stats)
    if unexpected_only:
        stat_nodes = [
            node
            for node in stat_nodes
            if not node.children and node.stats.unexpected > 0
        ]

    for node in stat_nodes:
        node_stats = node.stats
        result_type = {'pkg': 'package', 'session': 'session', 'test': 'test'}.get(
            node.type,
            node.type,
        )
        lines.append(
            '| {result_id} | {result_type} | {path} | {objective} | {comments} | '
            '{passed} | {failed} | '
            '{passed_nok} | {failed_nok} | {skipped} | {skipped_nok} | '
            '{abnormal} | {total} | {nok} |'.format(
                result_id=_cell(node.result_id),
                result_type=_cell(result_type),
                path=_cell(' / '.join(node.path)),
                objective=_cell(node.objective),
                comments=_cell(_comments_text(node.comments)),
                passed=node_stats.passed,
                failed=node_stats.failed,
                passed_nok=node_stats.passed_unexpected,
                failed_nok=node_stats.failed_unexpected,
                skipped=node_stats.skipped,
                skipped_nok=node_stats.skipped_unexpected,
                abnormal=node_stats.abnormal,
                total=node_stats.total,
                nok=node_stats.unexpected,
            ),
        )

    if not stat_nodes:
        lines.append(
            '| - | - | - | - | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |',
        )
        if unexpected_only:
            lines.extend(
                [
                    '',
                    '*No unexpected or abnormal result leaves found.*',
                ],
            )

    lines.extend(
        [
            '',
            '*Use a test row Result ID with `get_run_leaf_results` to inspect '
            'its concrete executions.*',
        ],
    )
    return '\n'.join(lines)


def _expected_result_text(expected_results) -> str:
    values = [item.result_type for item in expected_results if item.result_type]
    return ', '.join(values) if values else '-'


def render_run_leaf_results(payload: RunLeafResultsPayload) -> str:
    leaf = payload.leaf
    pagination = payload.pagination
    lines = [
        f'# Leaf Results: {_cell(leaf.test_name)}',
        '',
        f'Path: `{_cell(" / ".join(leaf.path))}`',
        f'Aggregate leaf: `{_cell(leaf.result_id)}`',
        f'Run: `{_cell(leaf.run_id)}`',
        f'Requirements: `{_cell(payload.requirements or "none")}`',
        '',
        (
            '| Result ID | Start | Obtained | Expected | Classification | Verdicts | '
            'Artifacts |'
        ),
        '|---:|---|---|---|---|---|---:|',
    ]
    for result in payload.results:
        obtained = result.obtained_result
        lines.append(
            f'| {_cell(result.result_id)} | {_cell(result.start)} | '
            f'{_cell(obtained.result_type)} | '
            f'{_cell(_expected_result_text(result.expected_results))} | '
            f'{_cell(result.classification)} | '
            f'{_cell(obtained.verdicts)} | '
            f'{len(result.artifacts)} |',
        )
    if not payload.results:
        lines.append('| - | - | - | - | - | - | 0 |')

    page = 1
    if pagination.previous:
        page = int(pagination.previous.split('=')[1]) + 1
    lines.extend(
        [
            '',
            (
                f'*Page {page} | {pagination.count} results | '
                f'previous: {pagination.previous or "-"} | '
                f'next: {pagination.next or "-"}*'
            ),
        ],
    )
    return '\n'.join(lines)
