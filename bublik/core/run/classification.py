# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 OKTET Labs Ltd. All rights reserved.

from __future__ import annotations

from django.db import transaction

from bublik.core.logging import get_task_or_server_logger
from bublik.core.run.data import get_tags_by_runs, get_verdicts
from bublik.data import models


class ClassificationService:
    """
    Matcher engine: applies active IssueRules to a run's results, creating
    RuleResult stamps. The test path is always required for a match;
    parameters and verdicts are matched as a subset when non-empty (an empty
    value means that criterion is not applied). Tag matching is a run-level
    gate, since all results in a run share the run's tags.
    """

    @staticmethod
    def result_param_dict(result: models.TestIterationResult) -> dict:
        """
        Build a {name: value} dict of a result's test arguments.

        Args:
            result: The test iteration result

        Returns:
            Dictionary mapping argument names to their values
        """
        return {a.name: a.value for a in result.iteration.test_arguments.all()}

    @staticmethod
    def result_verdict_set(result: models.TestIterationResult) -> set[str]:
        """
        Collect a result's verdict strings.

        Args:
            result: The test iteration result

        Returns:
            Set of verdict values attached to the result
        """
        return set(
            result.meta_results.filter(meta__type='verdict').values_list(
                'meta__value',
                flat=True,
            ),
        )

    @staticmethod
    def rule_matches_run_tags(rule: models.IssueRule, run: models.TestIterationResult) -> bool:
        """
        Check the run-level tag gate for a rule.

        Args:
            rule: The issue rule to test
            run: The run whose tags are checked against the rule

        Returns:
            True if rule.tags is empty (no gate) or is a subset of the run's
            tags (important + relevant); False otherwise
        """
        if not rule.tags:
            return True

        important_by_run, relevant_by_run = get_tags_by_runs([run])
        universe = set(important_by_run.get(run.id, [])) | set(
            relevant_by_run.get(run.id, []),
        )
        return set(rule.tags).issubset(universe)

    @staticmethod
    def matching_results(
        rule: models.IssueRule,
        run: models.TestIterationResult,
    ) -> list[models.TestIterationResult]:
        """
        Find results in a run that match a rule.

        A result matches when its test equals rule.test and, for each
        non-empty matcher field on the rule (parameters, verdicts), the
        rule's captured value is a subset of the result's own value. The
        run-level tag gate (rule.tags) is checked once via
        rule_matches_run_tags before iterating over the rule's test results.

        Args:
            rule: The issue rule to match
            run: The run whose results are searched

        Returns:
            List of matching TestIterationResult instances
        """
        if not ClassificationService.rule_matches_run_tags(rule, run):
            return []

        # Arguments and verdicts of all the rule's test results in the run are
        # loaded in batches, not by queries per result.
        test_results = list(
            models.TestIterationResult.objects.filter(
                test_run=run,
                iteration__test_id=rule.test_id,
            )
            .select_related('iteration')
            .prefetch_related('iteration__test_arguments'),
        )
        verdicts_by_result = get_verdicts(test_results) if rule.verdicts else {}

        matched = []
        for result in test_results:
            if rule.parameters and not (
                rule.parameters.items()
                <= ClassificationService.result_param_dict(result).items()
            ):
                continue
            if rule.verdicts and not set(rule.verdicts).issubset(
                verdicts_by_result.get(result.id, ()),
            ):
                continue
            matched.append(result)
        return matched

    @staticmethod
    def apply_active_rules(run: models.TestIterationResult) -> int:
        """
        Recompute import-origin RuleResult stamps for a run from the project's
        active rules. Idempotent: drops previous origin='import' stamps for this
        run, then rebuilds them from the current set of active rules, so the
        stamps of deactivated rules are dropped. Manual stamps (manual_persistent
        / manual_oneoff) are never touched. Only the rules of open issues apply:
        closing an issue deactivates its rules. A rule that fails to apply is
        logged and skipped (its own stamps are rolled back), so one broken rule
        can't block the others.

        Args:
            run: The run to (re)apply active rules to, typically right after import

        Returns:
            Number of RuleResult stamps created
        """
        logger = get_task_or_server_logger()
        with transaction.atomic():
            models.RuleResult.objects.filter(
                result__test_run=run,
                origin=models.RuleResultOrigin.IMPORT,
            ).delete()

            rules = models.IssueRule.objects.filter(
                issue__project_id=run.project_id,
                issue__state=models.IssueState.OPEN,
                active=True,
            )
            created = 0
            for rule in rules:
                try:
                    with transaction.atomic():
                        rule_created = 0
                        for result in ClassificationService.matching_results(rule, run):
                            _, made = models.RuleResult.objects.get_or_create(
                                result=result,
                                issue_rule=rule,
                                defaults={'origin': models.RuleResultOrigin.IMPORT},
                            )
                            rule_created += int(made)
                except Exception:
                    logger.exception(
                        f'skipping classification rule {rule.id}: failed on run {run.id}'
                    )
                else:
                    created += rule_created
        return created

    @staticmethod
    def apply_active_rules_manual(
        run: models.TestIterationResult,
        actor: models.User | None = None,
    ) -> int:
        """
        Apply the project's active rules to an already-imported run on demand.

        Existing RuleResult stamps are never removed - this only adds stamps
        that are missing, so it is safe to call repeatedly on the same run.
        Only the rules of open issues apply: closing an issue deactivates its
        rules.
        A rule that fails to apply is logged and skipped (its own stamps are
        rolled back), so one broken rule can't block the others.

        Args:
            run: The run to apply active rules to
            actor: The user who triggered the action, stored as created_by
                on any new stamps

        Returns:
            Number of RuleResult stamps actually created
        """
        logger = get_task_or_server_logger()
        rules = models.IssueRule.objects.filter(
            issue__project_id=run.project_id,
            issue__state=models.IssueState.OPEN,
            active=True,
        )
        created = 0
        for rule in rules:
            try:
                with transaction.atomic():
                    rule_created = 0
                    for result in ClassificationService.matching_results(rule, run):
                        _, made = models.RuleResult.objects.get_or_create(
                            result=result,
                            issue_rule=rule,
                            defaults={
                                'origin': models.RuleResultOrigin.MANUAL_PERSISTENT,
                                'created_by': actor,
                            },
                        )
                        rule_created += int(made)
            except Exception:
                logger.exception(
                    f'skipping classification rule {rule.id}: failed on run {run.id}'
                )
            else:
                created += rule_created
        return created

    @staticmethod
    def runs_for_rules(rule_ids: list[int]) -> list[int]:
        """
        Get run IDs that have at least one stamp for any of the given rules.

        Args:
            rule_ids: The issue rule IDs to look up

        Returns:
            List of distinct TestIterationResult (run) IDs
        """
        return list(
            models.RuleResult.objects.filter(issue_rule_id__in=rule_ids)
            .values_list('result__test_run_id', flat=True)
            .distinct(),
        )

    @staticmethod
    def runs_for_issues(issue_ids: list[int]) -> list[int]:
        """
        Get run IDs that have at least one stamp for any rule of any of the given issues.

        Args:
            issue_ids: The issue IDs to look up

        Returns:
            List of distinct TestIterationResult (run) IDs
        """
        return list(
            models.RuleResult.objects.filter(issue_rule__issue_id__in=issue_ids)
            .values_list('result__test_run_id', flat=True)
            .distinct(),
        )
