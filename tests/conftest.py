"""Shared pytest fixtures for unit and integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_python_source() -> str:
    """A representative Python source snippet for AST parser tests."""
    return '''
"""Module docstring."""

import os
from typing import Optional
from fastapi import APIRouter, Depends

router = APIRouter()


class MyModel:
    """A simple model class."""

    def __init__(self, name: str, value: int = 0) -> None:
        self.name = name
        self.value = value

    def compute(self) -> int:
        """Compute and return the value."""
        return self.value * 2


class ExtendedModel(MyModel):
    """Extended version."""

    extra: str = ""


@router.get("/items/{item_id}", response_model=MyModel, status_code=200)
async def get_item(item_id: int, db: Optional[str] = Depends(lambda: "db")) -> MyModel:
    """Get a single item by ID."""
    return MyModel(name=f"item_{item_id}", value=item_id)


@router.post("/items/", status_code=201)
async def create_item(item: MyModel) -> MyModel:
    """Create a new item."""
    return item
'''


@pytest.fixture
def fastapi_class_source() -> str:
    """Minimal FastAPI-like class for pattern detection tests."""
    return '''
from starlette.routing import Router

class APIRouter(Router):
    """FastAPI router extending Starlette."""

    def __init__(self, prefix: str = "") -> None:
        super().__init__()
        self.prefix = prefix

    def add_api_route(self, path: str, endpoint, **kwargs) -> None:
        """Register a route."""
        ...

    def get(self, path: str, **kwargs):
        """Decorator for GET routes."""
        def decorator(func):
            self.add_api_route(path, func, methods=["GET"], **kwargs)
            return func
        return decorator
'''
