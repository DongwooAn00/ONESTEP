from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed" / "shapefiles"


TARGETS = {
    "노드": "nodes",
    "링크": "links",
}


def compact(value: str) -> str:
    return value.replace(" ", "")


def find_zip(keyword: str) -> Path:
    for path in RAW_DIR.glob("*.zip"):
        if keyword in compact(path.name):
            return path
    raise FileNotFoundError(f"{keyword} ZIP 파일을 찾을 수 없습니다.")


def extract_components(zip_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path) as archive:
        for member in archive.infolist():
            suffix = Path(member.filename).suffix.lower()
            if suffix not in {".shp", ".shx", ".dbf", ".prj"}:
                continue
            output_path = target_dir / Path(member.filename).name
            output_path.write_bytes(archive.read(member))


def main() -> None:
    for keyword, dirname in TARGETS.items():
        extract_components(find_zip(keyword), OUT_DIR / dirname)


if __name__ == "__main__":
    main()
