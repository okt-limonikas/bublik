# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2016-2023 OKTET Labs Ltd. All rights reserved.
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict

from django.conf import settings
from django.http import HttpResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from drf_spectacular.utils import extend_schema
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.serializers import CharField, FloatField, Serializer
from rest_framework.viewsets import GenericViewSet


logger = logging.getLogger(__name__)


__all__ = [
    'ChatViewSet',
    'chat_stream_view',
]


class ChatRequestSerializer(Serializer):
    '''Serializer for chat request data.'''
    message = CharField(
        max_length=50000,
        help_text='The user message to send to the chat model',
    )
    system_message = CharField(
        max_length=10000,
        required=False,
        allow_blank=True,
        help_text='Optional system message to set the context',
    )
    model = CharField(
        max_length=100,
        required=False,
        help_text='The model to use for the chat completion',
    )
    temperature = FloatField(
        min_value=0.0,
        max_value=2.0,
        required=False,
        default=0.7,
        help_text='Controls randomness in the response (0.0 to 2.0)',
    )

class ChatResponseSerializer(Serializer):
    '''Serializer for chat response data.'''
    content = CharField(help_text='The chat response content')
    model = CharField(help_text='The model used for the response')
    finish_reason = CharField(help_text='The reason the response finished')
    usage = CharField(help_text='Token usage information', required=False)


class ChatViewSet(GenericViewSet):
    '''ViewSet for chat API endpoints using LangChain with OpenAI-compatible endpoints.'''

    def get_lm_studio_config(self) -> Dict[str, Any]:
        '''Get LM Studio configuration from Django settings.'''
        return {
            'base_url': getattr(settings, 'LM_STUDIO_BASE_URL', 'http://192.168.1.144:1234/v1'),
            'api_key': getattr(settings, 'LM_STUDIO_API_KEY', 'lm-studio'),
            'model': getattr(settings, 'LM_STUDIO_DEFAULT_MODEL', 'local-model'),
            'timeout': getattr(settings, 'LM_STUDIO_TIMEOUT', 60),
        }

    def create_chat_model(
        self,
        model_name: str | None = None,
        temperature: float = 0.7,
        streaming: bool = True,
    ) -> ChatOpenAI:
        '''Create and configure the ChatOpenAI model.'''
        config = self.get_lm_studio_config()

        return ChatOpenAI(
            base_url=config['base_url'],
            api_key=config['api_key'],
            model=model_name or config['model'],
            temperature=temperature,
            timeout=config['timeout'],
            streaming=streaming,
        )

    async def generate_chat_stream(
        self,
        chat_model: ChatOpenAI,
        messages: list,
    ) -> AsyncGenerator[str, None]:
        """Generate streaming chat responses using LangChain's astream method."""
        try:
            # Use LangChain's astream method for proper async streaming
            async for chunk in chat_model.astream(messages):
                if hasattr(chunk, 'content') and chunk.content:
                    # Format as Server-Sent Events (SSE)
                    data = {
                        'type': 'content',
                        'content': chunk.content,
                    }
                    yield f'data: {json.dumps(data)}\n\n'

            # Send completion signal
            completion_data = {
                'type': 'done',
                'content': '',
                'finish_reason': 'stop',
            }
            yield f'data: {json.dumps(completion_data)}\n\n'

        except Exception as e:
            logger.error(f'Error in chat streaming: {e!s}')
            error_data = {
                'type': 'error',
                'content': f'Error: {e!s}',
                'error_code': 'streaming_error',
            }
            yield f'data: {json.dumps(error_data)}\n\n'

    def sync_stream_wrapper(self, async_generator):
        '''Wrapper to convert async generator to sync for Django StreamingHttpResponse.'''
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async_iter = async_generator.__aiter__()
            while True:
                try:
                    yield loop.run_until_complete(async_iter.__anext__())
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    @extend_schema(
        request=ChatRequestSerializer,
        responses={
            200: ChatResponseSerializer,
            400: {'description': 'Bad request'},
            500: {'description': 'Internal server error'},
        },
        description='Get chat completion (non-streaming) using LangChain with OpenAI-compatible endpoint',
    )
    @action(detail=False, methods=['post'])
    def complete(self, request):
        '''Get non-streaming chat completion from LangChain model.'''
        serializer = ChatRequestSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {'error': 'Invalid request data', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            message = serializer.validated_data['message']
            system_message = serializer.validated_data.get('system_message', '')
            model_name = serializer.validated_data.get('model')
            temperature = serializer.validated_data.get('temperature', 0.7)

            messages = []
            if system_message:
                messages.append(SystemMessage(content=system_message))
            messages.append(HumanMessage(content=message))

            chat_model = self.create_chat_model(
                model_name=model_name,
                temperature=temperature,
                streaming=False,
            )

            # Generate response using invoke method
            response_message = chat_model.invoke(messages)

            # Extract usage information if available
            usage_info = {}
            if hasattr(response_message, 'usage_metadata') and response_message.usage_metadata:
                usage_info = {
                    'prompt_tokens': response_message.usage_metadata.get('input_tokens', 0),
                    'completion_tokens': response_message.usage_metadata.get('output_tokens', 0),
                    'total_tokens': response_message.usage_metadata.get('total_tokens', 0),
                }

            config = self.get_lm_studio_config()
            return Response({
                'content': response_message.content,
                'model': model_name or config['model'],
                'finish_reason': 'stop',
                'usage': usage_info,
            })

        except ValueError as e:
            logger.error(f'Invalid parameter values: {e!s}')
            return Response(
                {'error': 'Invalid parameter values', 'details': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f'Unexpected error in chat completion: {e!s}')
            return Response(
                {'error': 'Internal server error', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        responses={
            200: {'description': 'Chat service health status'},
            503: {'description': 'Service unavailable'},
        },
        description='Check if the chat service is available',
    )
    @action(detail=False, methods=['get'])
    def health(self, request):
        '''Check chat service health.'''
        try:
            config = self.get_lm_studio_config()

            # Try to create a model instance to test connectivity
            chat_model = self.create_chat_model(
                streaming=False,
            )

            # Simple test message
            test_messages = [HumanMessage(content='Hello')]

            # Use a shorter timeout for health check
            chat_model.timeout = 10
            response = chat_model.invoke(test_messages)

            return Response({
                'status': 'healthy',
                'base_url': config['base_url'],
                'model': config['model'],
                'response_preview': response.content[:50] + '...' if len(response.content) > 50 else response.content,
            })

        except Exception as e:
            logger.error(f'Chat service health check failed: {e!s}')
            config = self.get_lm_studio_config()
            return Response({
                'status': 'unhealthy',
                'error': str(e),
                'base_url': config.get('base_url', 'unknown'),
                'model': config.get('model', 'unknown'),
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @extend_schema(
        responses={
            200: {'description': 'Available models list'},
        },
        description='Get list of available models from LM Studio',
    )
    @action(detail=False, methods=['get'])
    def models(self, request):
        '''Get available models from LM Studio.'''
        try:
            config = self.get_lm_studio_config()

            return Response({
                'models': [
                    {
                        'id': config['model'],
                        'object': 'model',
                        'created': None,
                        'owned_by': 'lm-studio',
                    },
                ],
                'base_url': config['base_url'],
            })

        except Exception as e:
            logger.error(f'Error getting models list: {e!s}')
            return Response({
                'error': 'Failed to get models list',
                'details': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@require_http_methods(['POST', 'OPTIONS'])
def chat_stream_view(request):
    '''Plain Django view for streaming chat responses to avoid DRF content negotiation issues.'''
    if request.method == 'OPTIONS':
        response = HttpResponse()
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return HttpResponse(
            json.dumps({'error': 'Invalid JSON data'}),
            status=400,
            content_type='application/json',
        )

    # Validate data manually
    message = data.get('message')
    if not message or len(message) > 50000:
        return HttpResponse(
            json.dumps({'error': 'Message is required and must be less than 50000 characters'}),
            status=400,
            content_type='application/json',
        )

    system_message = data.get('system_message', '')
    model_name = data.get('model')
    temperature = float(data.get('temperature', 0.7))

    if not (0.0 <= temperature <= 2.0):
        return HttpResponse(
            json.dumps({'error': 'Temperature must be between 0.0 and 2.0'}),
            status=400,
            content_type='application/json',
        )

    try:
        config = {
            'base_url': getattr(settings, 'LM_STUDIO_BASE_URL', 'http://192.168.1.144:1234/v1'),
            'api_key': getattr(settings, 'LM_STUDIO_API_KEY', 'lm-studio'),
            'model': getattr(settings, 'LM_STUDIO_DEFAULT_MODEL', 'local-model'),
            'timeout': getattr(settings, 'LM_STUDIO_TIMEOUT', 60),
        }

        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=message))

        # Create chat model
        chat_model = ChatOpenAI(
            base_url=config['base_url'],
            api_key=config['api_key'],
            model=model_name or config['model'],
            temperature=temperature,
            timeout=config['timeout'],
            streaming=True,
        )

        async def generate_stream():
            try:
                async for chunk in chat_model.astream(messages):
                    if hasattr(chunk, 'content') and chunk.content:
                        data = {
                            'type': 'content',
                            'content': chunk.content,
                        }
                        yield f'data: {json.dumps(data)}\n\n'

                completion_data = {
                    'type': 'done',
                    'content': '',
                    'finish_reason': 'stop',
                }
                yield f'data: {json.dumps(completion_data)}\n\n'

            except Exception as e:
                logger.error(f'Error in chat streaming: {e!s}')
                error_data = {
                    'type': 'error',
                    'content': f'Error: {e!s}',
                    'error_code': 'streaming_error',
                }
                yield f'data: {json.dumps(error_data)}\n\n'

        def sync_wrapper():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async_iter = generate_stream().__aiter__()
                while True:
                    try:
                        yield loop.run_until_complete(async_iter.__anext__())
                    except StopAsyncIteration:
                        break
            finally:
                loop.close()

        response = StreamingHttpResponse(
            sync_wrapper(),
            content_type='text/event-stream',
        )

        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'

        return response

    except ValueError as e:
        logger.error(f'Invalid parameter values: {e!s}')
        return HttpResponse(
            json.dumps({'error': 'Invalid parameter values', 'details': str(e)}),
            status=400,
            content_type='application/json',
        )
    except Exception as e:
        logger.error(f'Unexpected error in chat stream: {e!s}')
        return HttpResponse(
            json.dumps({'error': 'Internal server error', 'details': str(e)}),
            status=500,
            content_type='application/json',
        )
