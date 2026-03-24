# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2016-2026 OKTET Labs Ltd. All rights reserved.

from __future__ import annotations

import typing

from django.conf import settings
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.viewsets import GenericViewSet

from bublik.analytics.models import AnalyticsEvent
from bublik.core.analytics.services import AnalyticsService
from bublik.core.auth import auth_required


__all__ = ['AnalyticsViewSet']


MAX_EVENTS_PER_BATCH = AnalyticsService.MAX_EVENTS_PER_BATCH
MAX_PAYLOAD_LENGTH = AnalyticsService.MAX_PAYLOAD_LENGTH
MAX_IMPORT_EVENTS = AnalyticsService.MAX_IMPORT_EVENTS


class AnalyticsEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticsEvent
        fields: typing.ClassVar[list[str]] = [
            'id',
            'event_uuid',
            'event_type',
            'event_name',
            'path',
            'anon_id',
            'session_id',
            'browser_name',
            'browser_version',
            'os_name',
            'user_agent',
            'app_version',
            'payload',
            'occurred_at',
            'created_at',
        ]


class AnalyticsCollectEventSerializer(serializers.Serializer):
    event_uuid = serializers.UUIDField(required=False)
    event_type = serializers.CharField(max_length=64)
    event_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
    )
    path = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=512,
    )
    anon_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
    )
    session_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
    )
    browser_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
    )
    browser_version = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
    )
    os_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
    )
    user_agent = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=512,
    )
    app_version = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
    )
    payload = serializers.JSONField(required=False)
    occurred_at = serializers.DateTimeField(required=False)

    def validate_payload(self, value):
        return AnalyticsService.validate_payload_size(value, MAX_PAYLOAD_LENGTH)


class AnalyticsCollectRequestSerializer(serializers.Serializer):
    events = AnalyticsCollectEventSerializer(many=True, allow_empty=False)

    def validate_events(self, value):
        if len(value) > MAX_EVENTS_PER_BATCH:
            msg = f'Only up to {MAX_EVENTS_PER_BATCH} events can be ingested per request'
            raise ValidationError(msg)
        return value


class AnalyticsImportRequestSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField()
    events = AnalyticsCollectEventSerializer(many=True, allow_empty=False)

    def validate_events(self, value):
        if len(value) > MAX_IMPORT_EVENTS:
            msg = f'Only up to {MAX_IMPORT_EVENTS} events can be imported per request'
            raise ValidationError(msg)
        return value


class AnalyticsCollectThrottle(SimpleRateThrottle):
    scope = 'analytics_collect'
    rate = getattr(settings, 'ANALYTICS_COLLECT_THROTTLE_RATE', '120/min')

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class AnalyticsViewSet(ListModelMixin, GenericViewSet):
    serializer_class = AnalyticsEventSerializer
    filter_backends: typing.ClassVar[list] = []

    def get_queryset(self):
        return AnalyticsService.get_filtered_queryset(self.request.query_params)

    @auth_required(as_admin=True)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['post'], throttle_classes=[AnalyticsCollectThrottle])
    def collect(self, request):
        serializer = AnalyticsCollectRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = typing.cast('dict[str, typing.Any]', serializer.validated_data)

        result = {'received': AnalyticsService.collect_events(validated_data['events'])}

        return Response(
            data=result,
            status=status.HTTP_202_ACCEPTED,
        )

    @auth_required(as_admin=True)
    @action(detail=False, methods=['get'])
    def overview(self, request):
        queryset = self.get_queryset()
        return Response(data=AnalyticsService.get_overview(queryset))

    @auth_required(as_admin=True)
    @action(detail=False, methods=['get'])
    def facets(self, request):
        queryset = self.get_queryset()
        return Response(data=AnalyticsService.get_facets(queryset))

    @auth_required(as_admin=True)
    @action(detail=False, methods=['get'])
    def charts(self, request):
        queryset = self.get_queryset()
        return Response(
            data=AnalyticsService.get_charts_for_query(queryset, request.query_params),
        )
