"""Update the PHP source version and checksum in matching Dockerfiles."""

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


DOWNLOADS_URL = "https://www.php.net/downloads.php?source=Y"
ROOT = Path(__file__).resolve().parent
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
SHA256_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")


class SourceDownloadsParser(HTMLParser):
    """Collect download links and text belonging to each list item."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.items: list[tuple[list[str], str]] = []
        self.links: list[str] = []
        self.content: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            if self.depth == 0:
                self.links = []
                self.content = []
            self.depth += 1
        if tag == "a" and self.depth:
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.items.append((self.links, " ".join(self.content)))

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.content.append(data)


def get_sha256(version: str) -> str:
    try:
        with urlopen(DOWNLOADS_URL, timeout=20) as response:
            html = response.read().decode("utf-8")
    except (OSError, URLError, UnicodeError) as exc:
        raise ValueError(f"无法读取 PHP 下载页: {exc}") from exc

    parser = SourceDownloadsParser()
    parser.feed(html)
    filename = f"php-{version}.tar.xz"
    hashes = {
        match.group().lower()
        for links, content in parser.items
        if any(Path(urlparse(link).path).name == filename for link in links)
        for match in SHA256_RE.finditer(content)
    }
    if len(hashes) != 1:
        raise ValueError(f"PHP 下载页中未找到 {filename} 的唯一 SHA256")
    return hashes.pop()


def updated_content(content: str, version: str, sha256: str) -> str:
    replacements = {
        "PHP_VERSION": f"ENV PHP_VERSION={version}",
        "PHP_URL": (
            f'ENV PHP_URL="https://www.php.net/distributions/php-{version}.tar.xz" '
            f'PHP_ASC_URL="https://www.php.net/distributions/php-{version}.tar.xz.asc"'
        ),
        "PHP_SHA256": f'ENV PHP_SHA256="{sha256}"',
    }
    for name, replacement in replacements.items():
        content, count = re.subn(rf"(?m)^ENV {name}=.*$", replacement, content)
        if count != 1:
            raise ValueError(f"Dockerfile 中 ENV {name} 出现 {count} 次，预期 1 次")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description="更新指定 PHP 版本的 Dockerfile")
    parser.add_argument("--ver", required=True, help="完整 PHP 版本，例如 8.4.26")
    args = parser.parse_args()

    match = VERSION_RE.fullmatch(args.ver)
    if not match:
        parser.error("--ver 必须是主版本.次版本.补丁版本，例如 8.4.26")
    version_dir = ROOT / f"{match[1]}.{match[2]}"
    dockerfiles = sorted(version_dir.glob("*/*/Dockerfile"))
    if not dockerfiles:
        parser.error(f"未找到 {version_dir.relative_to(ROOT)}/*/*/Dockerfile")

    try:
        sha256 = get_sha256(args.ver)
        changes = [(path, updated_content(path.read_text(), args.ver, sha256)) for path in dockerfiles]
        for path, content in changes:
            path.write_text(content)
            print(f"已更新 {path.relative_to(ROOT)}: PHP {args.ver}, SHA256 {sha256}")
    except (ValueError, OSError) as exc:
        print(f"更新失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
