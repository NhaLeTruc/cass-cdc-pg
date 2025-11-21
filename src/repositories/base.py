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
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the connection is healthy"""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the connection"""
        pass
