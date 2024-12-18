# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2024 OKTET Labs Ltd. All rights reserved.

from enum import Enum

from django.db import models

from bublik.data.models.user import User


__all__ = [
    'ConfigTypes',
    'GlobalConfigNames',
    'Config',
]


class ConfigTypes(models.TextChoices):
    '''
    All available configuration types.
    '''

    GLOBAL = 'global'
    REPORT = 'report'

    @classmethod
    def all(cls):
        return [value.value for name, value in vars(cls).items() if name.isupper()]


class GlobalConfigNames(str, Enum):
    '''
    All available global configuration names.
    '''

    PER_CONF = 'per_conf'

    def __str__(self):
        return self.value

    @classmethod
    def all(cls):
        return [value.value for name, value in vars(cls).items() if name.isupper()]


class Config(models.Model):
    '''
    Configurations.
    '''

    created = models.DateTimeField(help_text='Timestamp of the config creation.')
    type = models.CharField(
        choices=ConfigTypes.choices,
        max_length=16,
        help_text='Configuration type.',
    )
    name = models.TextField(max_length=32, help_text='Configuration name.')
    version = models.IntegerField(default=0, help_text='Configuration version.')
    is_active = models.BooleanField()
    description = models.TextField(
        blank=True,
        help_text='Description of the configuration.',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='config',
        help_text='The user who created the configuration object.',
    )
    content = models.JSONField(help_text='Configuration data.')

    class Meta:
        db_table = 'bublik_config'
        unique_together = ('type', 'name', 'version')

    @classmethod
    def get_latest_version(cls, config_type, config_name):
        return (
            Config.objects.filter(type=config_type, name=config_name).order_by('version').last()
        )

    @classmethod
    def get_active_version(cls, config_type, config_name):
        return Config.objects.filter(
            type=config_type,
            name=config_name,
            is_active=True,
        ).first()

    @classmethod
    def get_all_versions(cls, config_type, config_name):
        return (
            Config.objects.filter(
                type=config_type,
                name=config_name,
            )
            .order_by('-is_active', '-created')
            .values('id', 'version', 'is_active', 'description', 'created')
        )

    def activate(self):
        active = self.__class__.get_active_version(self.type, self.name)
        if active:
            active.is_active = False
            active.save()
        self.is_active = True
        self.save()

    def delete(self, *args, **kwargs):
        config_type = self.type
        config_name = self.name
        config_active = self.is_active
        super().delete(*args, **kwargs)
        if config_active:
            latest = self.get_latest_version(config_type, config_name)
            if latest:
                latest.activate()

    def __repr__(self):
        return (
            f'Config(created={self.created!r}, type={self.type!r}, name={self.name!r}, '
            f'version={self.version!r}, is_active={self.is_active!r}, '
            f'description={self.description!r}, user={self.user!r})'
        )
