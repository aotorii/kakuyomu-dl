from errors import FetchError
from models import Episode, RawParagraph, TocEntry, WorkImage, WorkMeta

from .base import BaseScraper
from .hameln import HamelnScraper
from .kakuyomu import KakuyomuScraper
from .naro import NaroScraper
from .novelup import NupScraper
from .akatsuki import AkatsukiScraper
