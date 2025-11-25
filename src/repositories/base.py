"""
Abstract base class for repository pattern implementation.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class AbstractRepository(ABC):
    """Base repository interface for data access operations"""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the data store"""
        raise NotImplementedError("Subclass must implement connect()")

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the connection is healthy"""
        raise NotImplementedError("Subclass must implement health_check()")

    @abstractmethod
    def close(self) -> None:
        """Close the connection"""
        raise NotImplementedError("Subclass must implement close()")
