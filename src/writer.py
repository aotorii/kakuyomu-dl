import logging
from pathlib import Path
from string import Template
from parser import ParsedChapter, BlockType
from paths import OUT_DIR

logger = logging.getLogger(__name__)

XHTML_TEMPLATE = Template("""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html
 xmlns="http://www.w3.org/1999/xhtml"
 xmlns:epub="http://www.idpf.org/2007/ops"
 xml:lang="ja"
>
<head>
<meta charset="UTF-8"/>
<title>$title</title>
<link rel="stylesheet" type="text/css" href="../style/style.css"/>
</head>
<body class="p-text">
<div class="main">
$body_content
</div>
</body>
</html>
""")

P_TEMPLATE = Template('<p>$text</p>')

CATEGORY_TEMPLATE = Template('<p class="chapter-category">$text</p>')

TITLE_TEMPLATE = Template('<h1 id="start" class="chapter-title">$text</h1>')

BLANK_LINE = '<p><br/></p>'


class XhtmlWriter:
    def __init__(
        self,
        series_id: str = "",
        out_dir: str | Path = OUT_DIR / "{series_id}/xhtml",
        filename_tmpl: str = "{index:04d}_{episode_id}.xhtml",
        overwrite: bool = True,
    ):
        self.out_dir = Path(str(out_dir).format(series_id=series_id))
        self.filename_tmpl = filename_tmpl
        self.overwrite = overwrite

    def write(self, chapter: ParsedChapter) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)

        filename = self.filename_tmpl.format(
            index=chapter.index,
            episode_id=chapter.episode_id,
        )
        path = self.out_dir / filename

        if path.exists() and not self.overwrite:
            logger.info(f"Skipping existing file: {path}")
            return path

        xhtml = self._render(chapter)
        path.write_text(xhtml, encoding="utf-8")
        logger.info(f"Wrote: {path}")
        return path

    def write_many(self, chapters: list[ParsedChapter]) -> list[Path]:
        return [self.write(ch) for ch in chapters]

    def _render(self, chapter: ParsedChapter) -> str:
        lines: list[str] = []

        if chapter.category:
            lines.append(CATEGORY_TEMPLATE.substitute(text=_escape(chapter.category)))

        lines.append(TITLE_TEMPLATE.substitute(text=_escape(chapter.title)))

        for block in chapter.blocks:
            if block.type == BlockType.PARAGRAPH:
                lines.append(f'<p>{block.text.replace("&", "&amp;")}</p>')
                # lines.append(P_TEMPLATE.substitute(text=_escape(block.text)))

            elif block.type == BlockType.SCENE_BREAK:
                if block.text:
                    lines.append(BLANK_LINE)
                    lines.append(f'<p class="scene-break-deco">{_escape(block.text)}</p>')
                    lines.append(BLANK_LINE)
                else:
                    lines.append(BLANK_LINE)

        body_content = "\n".join(lines)

        return XHTML_TEMPLATE.substitute(
            title=_escape(chapter.title),
            body_content=body_content,
        )


def _escape(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&apos;")
    return text
