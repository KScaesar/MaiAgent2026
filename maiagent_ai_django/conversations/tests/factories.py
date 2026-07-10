from __future__ import annotations

import factory
from factory import Faker
from factory.django import DjangoModelFactory

from maiagent_ai_django.conversations.models import Conversation
from maiagent_ai_django.conversations.models import Message
from maiagent_ai_django.conversations.models import ModelRoute
from maiagent_ai_django.conversations.models import SceneConfig


class SceneConfigFactory(DjangoModelFactory):
    name = factory.Sequence(lambda n: f"scene-{n}")
    scene_type = SceneConfig.SceneType.CUSTOMER_SERVICE
    default_settings = factory.LazyFunction(dict)
    is_active = True

    class Meta:
        model = SceneConfig


class ConversationFactory(DjangoModelFactory):
    user = factory.SubFactory("maiagent_ai_django.users.tests.factories.UserFactory")
    scene = factory.SubFactory(SceneConfigFactory)
    status = Conversation.Status.OPEN

    class Meta:
        model = Conversation


class MessageFactory(DjangoModelFactory):
    conversation = factory.SubFactory(ConversationFactory)
    sender_type = Message.SenderType.USER
    content = Faker("sentence")
    status = Message.Status.COMPLETED

    class Meta:
        model = Message


class ModelRouteFactory(DjangoModelFactory):
    scene = factory.SubFactory(SceneConfigFactory)
    model_name = factory.Sequence(lambda n: f"model-{n}")
    order = 0
    weight = 1
    is_enabled = True

    class Meta:
        model = ModelRoute
