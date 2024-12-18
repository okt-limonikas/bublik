# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2024 OKTET Labs Ltd. All rights reserved.

import logging
import re
import typing

from django.contrib.postgres.fields import JSONField
from django.core.management import call_command
from django_filters import rest_framework as filters
import per_conf
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from bublik.core.auth import auth_required
from bublik.core.config.filters import ConfigFilter
from bublik.core.queries import get_or_none
from bublik.data.models import Config, ConfigTypes, GlobalConfigNames
from bublik.data.serializers import ConfigSerializer


logger = logging.getLogger('')


class ConfigFilterSet(filters.FilterSet):
    class Meta:
        model = Config
        fields: typing.ClassVar = ['type', 'name', 'is_active', 'version']
        filter_overrides: typing.ClassVar = {
            JSONField: {
                'filter_class': filters.CharFilter,
                'extra': lambda f: {
                    'lookup_expr': 'icontains',
                },
            },
        }


class ConfigViewSet(ModelViewSet):
    queryset = Config.objects.all()
    serializer_class = ConfigSerializer
    filterset_class = ConfigFilterSet

    def filter_queryset(self, queryset):
        return ConfigFilter(queryset=self.queryset).qs

    def get_or_create(self, data):
        serializer = self.get_serializer(data=data)
        serializer.update_data()
        serializer.is_valid(raise_exception=True)
        return serializer.get_or_create(serializer.validated_data)

    @auth_required(as_admin=True)
    @action(detail=False, methods=['post'])
    def create_by_per_conf(self, request, *args, **kwargs):
        '''
        Create global config object by per_conf.py (if it does not exist).
        Return a created object or an existing per_conf global config object.
        Request: GET api/v2/config/create_by_per_conf.
        '''
        global_config = get_or_none(
            Config.objects,
            type=ConfigTypes.GLOBAL,
            name=GlobalConfigNames.PER_CONF,
        )
        if global_config:
            return Response(
                self.get_serializer(global_config).data,
                status=status.HTTP_200_OK,
            )

        # convert per_conf.py into dict
        per_conf_dict = {}
        args = dir(per_conf)
        args = [arg for arg in args if not re.fullmatch(r'__.+?__', arg)]
        per_conf_dict = {arg: getattr(per_conf, arg, None) for arg in args}

        # leave only valid attributes
        schema = self.serializer_class.get_json_schema(
            ConfigTypes.GLOBAL,
            GlobalConfigNames.PER_CONF,
        )
        valid_attributes = schema.get('properties', {}).keys()
        per_conf_dict = {k: v for k, v in per_conf_dict.items() if k in valid_attributes}

        # convert tuple into list
        if 'RUN_STATUS_BY_NOK_BORDERS' in per_conf_dict:
            per_conf_dict['RUN_STATUS_BY_NOK_BORDERS'] = list(
                per_conf_dict['RUN_STATUS_BY_NOK_BORDERS'],
            )

        # create a configuration object, skipping content validation
        data = {
            'type': ConfigTypes.GLOBAL,
            'name': GlobalConfigNames.PER_CONF,
            'description': 'The main project config',
            'is_active': True,
            'content': per_conf_dict,
        }
        serializer = self.get_serializer(data=data)
        serializer.update_data()
        config, created = serializer.get_or_create(serializer.initial_data)

        # reformat the content according to the current JSON schema, validate
        call_command(
            'reformat_configs',
            '-t',
            ConfigTypes.GLOBAL,
            '-n',
            GlobalConfigNames.PER_CONF,
        )

        config_data = self.get_serializer(config).data
        if not created:
            return Response(config_data, status=status.HTTP_400_BAD_REQUEST)
        return Response(config_data, status=status.HTTP_201_CREATED)

    @auth_required(as_admin=True)
    def create(self, request, *args, **kwargs):
        '''
        Create config with passed type, name, description and content
        (if object with the same content does not exist).
        Return a created object or an existing object with the passed content.
        Request: POST api/v2/config.
        '''
        data = {
            k: v
            for k, v in request.data.items()
            if k in ['type', 'name', 'is_active', 'description', 'content']
        }
        config, created = self.get_or_create(data)
        config_data = self.get_serializer(config).data
        if not created:
            return Response(config_data, status=status.HTTP_400_BAD_REQUEST)
        return Response(config_data, status=status.HTTP_201_CREATED)

    @auth_required(as_admin=True)
    def partial_update(self, request, *args, **kwargs):
        '''
        Update or create new version of the config by changing its description or content.
        Request: PATCH api/v2/config/<ID>.
        '''
        config = self.get_object()

        # prepare data for updating/creating a new version
        config_data = self.get_serializer(config).data
        updated_data = {
            'type': config_data['type'],
        }
        for attr in ['name', 'description', 'is_active', 'content']:
            updated_data[attr] = (
                request.data[attr] if attr in request.data else config_data[attr]
            )

        if 'name' in request.data:
            # check the passed name for uniqueness
            same_name_configs = Config.objects.filter(
                type=updated_data['type'],
                name=updated_data['name'],
            )
            if same_name_configs:
                msg = f'A {updated_data["type"]} configuration with the same name already exist'
                data = {
                    attr: updated_data[attr]
                    for attr in ['type', 'name', 'description', 'content']
                }
                return Response(
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    data={
                        'type': 'ValueError',
                        'message': msg,
                        'new_config_data': data,
                    },
                )
            if 'content' not in request.data:
                # rename all config versions
                serializer = self.get_serializer(config, data=updated_data, partial=True)
                serializer.validate_name(updated_data['name'])
                Config.get_all_versions(config_data['type'], config_data['name']).update(
                    name=updated_data['name'],
                )

        if 'content' in request.data:
            # create new object version
            new_config, created = self.get_or_create(updated_data)
            new_config_data = self.get_serializer(new_config).data
            if not created:
                return Response(new_config_data, status=status.HTTP_400_BAD_REQUEST)
            return Response(new_config_data, status=status.HTTP_201_CREATED)

        serializer = self.get_serializer(config, data=updated_data, partial=True)
        serializer.is_valid(raise_exception=True)

        if 'is_active' in request.data and updated_data['is_active']:
            config.activate()

        self.perform_update(serializer)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @auth_required(as_admin=True)
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @auth_required(as_admin=True)
    @action(detail=False, methods=['get'], url_path='schema')
    def get_schema(self, request, *args, **kwargs):
        '''
        Get the JSON schema by passed config type and name.
        Request: GET api/v2/config/get_schema/?type=<config_type>&name=<config_name>.
        '''
        config_type = request.query_params.get('type')
        config_name = request.query_params.get('name')
        serializer = self.get_serializer(data={'type': config_type, 'name': config_name})
        config_type = serializer.validate_type(config_type)
        config_name = serializer.validate_name(config_name)
        json_schema = self.serializer_class.get_json_schema(config_type, config_name)
        if json_schema:
            return Response(data=json_schema, status=status.HTTP_200_OK)
        msg = 'There is no JSON schema corresponding to the passed configuration type and name'
        return Response(
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            data={'type': 'ValueError', 'message': msg},
        )

    @auth_required(as_admin=True)
    @action(detail=True, methods=['get'])
    def all_versions(self, request, *args, **kwargs):
        '''
        Get all versions of passed config.
        Request: GET api/v2/config/<ID>/all_versions.
        '''
        config = self.get_object()
        config_data = self.get_serializer(config).data
        all_config_versions = Config.get_all_versions(config_data['type'], config_data['name'])

        data = {
            'type': config_data['type'],
            'name': config_data['name'],
            'all_config_versions': all_config_versions,
        }
        return Response(data, status=status.HTTP_200_OK)

    @auth_required(as_admin=True)
    def list(self, request):
        '''
        Of all configurations having the same type and name, if there are active ones,
        returns active ones, if there are none, returns the latest ones.
        '''
        configs_to_display = (
            Config.objects.order_by('type', 'name', '-is_active', '-created')
            .distinct('type', 'name')
            .values(
                'id',
                'version',
                'is_active',
                'type',
                'name',
                'description',
                'created',
            )
        )
        return Response(configs_to_display, status=status.HTTP_200_OK)

    @auth_required(as_admin=True)
    def retrieve(self, request, pk=None):
        return super().retrieve(request)
