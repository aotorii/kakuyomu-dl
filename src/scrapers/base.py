from abc import ABC, abstractmethod


class BaseScraper(ABC):
    @abstractmethod
    def fetch_meta_and_toc(self, series_id: str): ...
