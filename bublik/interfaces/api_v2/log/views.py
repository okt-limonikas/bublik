# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2016-2023 OKTET Labs Ltd. All rights reserved.

from html import escape

from django.http import FileResponse, Http404, HttpResponse
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import action
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from bublik.core.log.s3_logs import (
    LogGenerationError,
    list_generated_directory,
    list_run_directory,
    open_log_item,
    storage_for,
)
from bublik.core.log.services import LogService
from bublik.core.shortcuts import get_origin
from bublik.data.models import TestIterationResult
from bublik.data.serializers import TestIterationResultSerializer
from bublik.interfaces.api_v2.log.schemas import log_viewset_schema
from bublik.interfaces.api_v2.log.serializers import (
    LogHtmlResponseSerializer,
    LogJsonQuerySerializer,
    LogJsonResponseSerializer,
)


__all__ = [
    'LogViewSet',
    's3_log',
]


@log_viewset_schema
class LogViewSet(RetrieveModelMixin, GenericViewSet):
    queryset = TestIterationResult.objects.all()
    serializer_class = TestIterationResultSerializer

    @action(detail=True, methods=['get'])
    def json(self, request, pk=None):
        # Preserve explicit empty values so the optional field rejects ?page=.
        serializer = LogJsonQuerySerializer(data=request.query_params.dict())
        serializer.is_valid(raise_exception=True)
        page = serializer.validated_data.get('page')
        request_origin = request.get_host() if request else None

        # Let LogService handle validation and raise appropriate exceptions
        # The custom exception handler will format the response
        urls = LogService.get_json_log_urls(int(pk), page, request_origin)
        return Response(LogJsonResponseSerializer(urls).data)

    @action(detail=True, methods=['get'])
    def html(self, request, pk=None):
        # Let LogService handle validation and raise appropriate exceptions
        # The custom exception handler will format the response
        url = LogService.get_html_log_url(int(pk), get_origin(request))
        serializer = LogHtmlResponseSerializer(instance={'url': url})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def proxy(self, request):
        forward_url = request.query_params.get('url')

        # Let LogService handle validation and raise appropriate exceptions
        # The custom exception handler will format the response
        content = LogService.fetch_log_content(forward_url)
        return Response(data=content)


@require_http_methods(['GET', 'HEAD'])
def s3_log(request, bucket, key=''):
    """
    Serve a file of a run stored under an S3 logs base, generating missing
    JSON and HTML log pages from the run's bundle, as a TE log server does.
    A directory gets an index of what is in it; a run's json/ and html/ are
    generated whole for it.
    Route: /api/v2/logs/s3/<bucket>/<key>.
    """
    storage = storage_for(bucket, key)
    if storage is None:
        raise Http404

    if not key or key.endswith('/'):
        return _directory_listing(storage, key)

    try:
        item = open_log_item(storage, key)
    except LogGenerationError as error:
        return HttpResponse(error.message, status=503, content_type='text/plain')
    if item is None:
        raise Http404

    response = FileResponse(item.stream, content_type=item.content_type)
    if item.length is not None:
        response['Content-Length'] = str(item.length)
    return response


def _directory_listing(storage, prefix):
    try:
        generated = list_generated_directory(storage, prefix)
    except LogGenerationError as error:
        return HttpResponse(error.message, status=503, content_type='text/plain')
    directories, files = generated or list_run_directory(storage, prefix)
    if not directories and not files:
        raise Http404
    title = escape(f'{storage.target.bucket}/{prefix}')
    rows = [
        f'<li><a href="{escape(name)}">{escape(name)}</a></li>' for name in directories + files
    ]
    body = (
        f'<!DOCTYPE html><html><head><title>Index of {title}</title></head>'
        f'<body><h1>Index of {title}</h1><ul>{"".join(rows)}</ul></body></html>'
    )
    return HttpResponse(body, content_type='text/html; charset=utf-8')
