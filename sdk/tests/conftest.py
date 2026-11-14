from __future__ import annotations

import pytest
from fakes import Entity, EntityType, Task


@pytest.fixture
def username_task() -> Task:
    return Task(service="fake", input=Entity(type=EntityType.USERNAME, value="alice"))
