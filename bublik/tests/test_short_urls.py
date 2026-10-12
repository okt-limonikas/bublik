# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 OKTET Labs Ltd. All rights reserved.

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve

from bublik.interfaces.main_api import redirect_short


class ShortURLResolveTest(SimpleTestCase):
    def assert_resolves(self, path, view_endpoint_hash):
        prefix = f'/{settings.URL_PREFIX}' if settings.URL_PREFIX else ''
        match = resolve(f'{prefix}{path}')

        self.assertIs(match.func, redirect_short)
        self.assertEqual(match.kwargs['view_endpoint_hash'], view_endpoint_hash)

    def test_resolves_urlsafe_hash_with_dash(self):
        self.assert_resolves('/short/runs/-JLyw-1wQhw=', 'runs/-JLyw-1wQhw=')

    def test_resolves_urlsafe_hash_with_underscore(self):
        self.assert_resolves('/short/runs/ab_cd1wQhw=', 'runs/ab_cd1wQhw=')

    def test_resolves_hash_with_project_prefix(self):
        self.assert_resolves('/my-project/short/runs/-JLyw-1wQhw=', 'runs/-JLyw-1wQhw=')
