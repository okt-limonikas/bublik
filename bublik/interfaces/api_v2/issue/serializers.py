# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 OKTET Labs Ltd. All rights reserved.

from django.conf import settings
from rest_framework import serializers
from rest_framework.fields import empty

from bublik.core.issue_results import (
    IssueResultsService,
    ResultClassification,
    ResultProperty,
)
from bublik.data.models import IssueCategory, ResultStatus
from bublik.interfaces.api_v2.result.serializers import ResultDetailsSerializer
from bublik.interfaces.api_v2.run.serializers import RunIssueRuleSerializer


class ActionResultSerializer(serializers.Serializer):
    requested = serializers.IntegerField()
    updated = serializers.IntegerField()
    unchanged = serializers.IntegerField()
    not_found = serializers.IntegerField()


class BulkIdsRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class IssueListQuerySerializer(serializers.Serializer):
    state = serializers.CharField(required=False)
    project = serializers.IntegerField(required=False)
    category = serializers.CharField(required=False)
    rules = serializers.CharField(
        required=False,
        help_text="';'-separated rules states: enforced, dormant, deactivated, unruled.",
    )
    search = serializers.CharField(required=False)
    created_after = serializers.DateField(required=False)
    created_before = serializers.DateField(required=False)
    updated_after = serializers.DateField(required=False)
    updated_before = serializers.DateField(required=False)


class IssueRuleListQuerySerializer(serializers.Serializer):
    project = serializers.IntegerField(required=False)
    issue = serializers.IntegerField(required=False)
    search = serializers.CharField(required=False)
    category = serializers.CharField(required=False)
    active = serializers.CharField(required=False)
    expected = serializers.CharField(
        required=False,
        help_text="';'-separated dispositions: expected, unexpected, none.",
    )
    issue_state = serializers.CharField(
        required=False,
        help_text="';'-separated issue states: open, closed.",
    )
    tag = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text='Repeatable. Rules that captured any of the given tags.',
    )
    verdict = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text='Repeatable. Rules that captured any of the given verdicts.',
    )
    parameter = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Repeatable 'name=value'. Rules that captured any of them.",
    )
    created_after = serializers.DateField(required=False)
    created_before = serializers.DateField(required=False)


class DelimitedChoicesField(serializers.ListField):
    """
    A `;`-separated list of choices in one query parameter, the form the
    other listings take their enum-valued filters in.
    """

    def __init__(self, choices, **kwargs):
        super().__init__(child=serializers.ChoiceField(choices=choices), **kwargs)

    def get_value(self, dictionary):
        return dictionary.get(self.field_name, empty)

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = data.split(settings.QUERY_DELIMITER) if data else []
        return super().to_internal_value(data)


class IssueResultsQuerySerializer(serializers.Serializer):
    """
    The result table's filter bar, as query parameters. Repeatable
    parameters are repeated, one value each; the others take a
    `;`-separated list, as the plain result listing does.
    """

    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=IssueResultsService.MAX_PAGE_SIZE,
    )
    results = serializers.CharField(
        required=False,
        help_text=f"';'-separated obtained results: {', '.join(ResultStatus.all_statuses())}.",
    )
    result_properties = DelimitedChoicesField(
        ResultProperty.choices,
        required=False,
        help_text=f"';'-separated: {', '.join(ResultProperty.values)}.",
    )
    requirements = serializers.CharField(
        required=False,
        help_text="';'-separated. Results carrying every given requirement.",
    )
    category = DelimitedChoicesField(
        IssueCategory.choices,
        required=False,
        help_text=f"';'-separated stamp categories: {', '.join(IssueCategory.values)}.",
    )
    classification = DelimitedChoicesField(
        ResultClassification.choices,
        required=False,
        help_text=f"';'-separated: {', '.join(ResultClassification.values)}.",
    )
    verdict = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text='Repeatable. Results carrying every given verdict.',
    )
    artifact = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text='Repeatable. Results carrying every given artifact.',
    )
    parameter = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text=(
            "Repeatable 'name=value', or a bare name for an empty value. "
            'Results whose iteration carries every one.'
        ),
    )


class IssueResultsFacetsSerializer(serializers.Serializer):
    """
    Every value each filter can take over the issue's results, unfiltered.
    Served on its own: it depends on the issue alone, not on the page.
    """

    results = serializers.ListField(child=serializers.CharField())
    result_properties = serializers.ListField(child=serializers.CharField())
    verdicts = serializers.ListField(child=serializers.CharField())
    categories = serializers.ListField(child=serializers.CharField())
    classifications = serializers.ListField(child=serializers.CharField())
    artifacts = serializers.ListField(child=serializers.CharField())
    parameters = serializers.ListField(child=serializers.CharField())
    requirements = serializers.ListField(child=serializers.CharField())


class IssueResultsPaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)


class RunTagsSerializer(serializers.Serializer):
    important_tags = serializers.ListField(child=serializers.CharField())
    relevant_tags = serializers.ListField(child=serializers.CharField())


class IssueResultDetailsSerializer(ResultDetailsSerializer):
    """A result row with its run's tags, since the rows span runs."""

    run_tags = RunTagsSerializer()


class IssueResultsResponseSerializer(serializers.Serializer):
    pagination = IssueResultsPaginationSerializer()
    results = IssueResultDetailsSerializer(many=True)


class IssuePickerQuerySerializer(serializers.Serializer):
    project = serializers.IntegerField(required=False)
    search = serializers.CharField(required=False)
    state = serializers.CharField(required=False)
    test = serializers.CharField(required=False)


class IssuePickerOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    state = serializers.CharField()
    bug_key = serializers.CharField(allow_null=True)
    bug_url = serializers.CharField(allow_null=True)
    rules = RunIssueRuleSerializer(many=True)


class TestPickerQuerySerializer(serializers.Serializer):
    project = serializers.IntegerField(required=False)
    search = serializers.CharField(required=False)


class TestPickerOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    path = serializers.CharField()
