"""INI configuration helpers."""

from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable


PARAMETER_FILES = (
    "parameters_geometry.ini",
    "parameters_mesh.ini",
    "parameters_sampling.ini",
    "parameters_runs.ini",
    "parameters_post.ini",
)


def _split(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    delimiter = ";" if ";" in raw else ","
    return [part.strip() for part in raw.split(delimiter) if part.strip()]


def _cast_auto(value: str) -> Any:
    value = value.strip()
    if value.lower() == "auto":
        return "auto"
    try:
        if any(char in value.lower() for char in (".", "e")):
            return float(value)
        return int(value)
    except ValueError:
        return value


@dataclass(frozen=True)
class WorkflowConfig:
    root: Path
    parameter_dir: Path
    parser: ConfigParser

    @classmethod
    def load(cls, root: Path, parameter_dir: Path) -> "WorkflowConfig":
        parser = ConfigParser(interpolation=None)
        files = [parameter_dir / name for name in PARAMETER_FILES]
        missing = [str(path) for path in files if not path.is_file()]
        if missing:
            raise FileNotFoundError("Missing parameter file(s): " + ", ".join(missing))
        parser.read(files, encoding="utf-8")
        return cls(root=root, parameter_dir=parameter_dir, parser=parser)

    def has(self, section: str, option: str) -> bool:
        return self.parser.has_option(section, option)

    def get(self, section: str, option: str, fallback: Any | None = None) -> str:
        if self.parser.has_option(section, option):
            return self.parser.get(section, option).strip()
        if fallback is not None:
            return str(fallback)
        raise KeyError(f"Missing required parameter [{section}] {option}")

    def get_bool(self, section: str, option: str, fallback: bool | None = None) -> bool:
        if self.parser.has_option(section, option):
            return self.parser.getboolean(section, option)
        if fallback is not None:
            return fallback
        raise KeyError(f"Missing required boolean parameter [{section}] {option}")

    def get_int(self, section: str, option: str, fallback: int | None = None) -> int:
        if self.parser.has_option(section, option):
            return self.parser.getint(section, option)
        if fallback is not None:
            return fallback
        raise KeyError(f"Missing required integer parameter [{section}] {option}")

    def get_float(self, section: str, option: str, fallback: float | None = None) -> float:
        if self.parser.has_option(section, option):
            return self.parser.getfloat(section, option)
        if fallback is not None:
            return fallback
        raise KeyError(f"Missing required float parameter [{section}] {option}")

    def get_list(
        self,
        section: str,
        option: str,
        fallback: Iterable[Any] | None = None,
        cast: Callable[[str], Any] = _cast_auto,
    ) -> list[Any]:
        if not self.parser.has_option(section, option):
            return list(fallback or [])
        return [cast(part) for part in _split(self.parser.get(section, option))]

    def get_path(
        self,
        section: str,
        option: str,
        fallback: str | Path | None = None,
        allow_empty: bool = False,
    ) -> Path | None:
        raw = self.get(section, option, fallback=fallback or "")
        if not raw:
            if allow_empty:
                return None
            raise ValueError(f"Empty path for [{section}] {option}")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return path

    def get_vector(self, section: str, option: str, length: int = 3) -> tuple[float, ...]:
        raw = self.get(section, option)
        values = [float(part) for part in raw.replace(",", " ").split()]
        if len(values) != length:
            raise ValueError(f"[{section}] {option} must contain {length} values.")
        return tuple(values)

    @property
    def study_name(self) -> str:
        return self.get("study", "name")

    @property
    def study_dir(self) -> Path:
        return self.root / "runs" / self.study_name

    @property
    def results_dir(self) -> Path:
        return self.get_path("post", "results_dir") / self.study_name  # type: ignore[operator]

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {
            section: {
                option: self.parser.get(section, option).strip()
                for option in sorted(self.parser.options(section))
            }
            for section in sorted(self.parser.sections())
        }

    def fingerprint(self, sections: Iterable[str] | None = None) -> str:
        if sections is None:
            payload = self.as_dict()
        else:
            wanted = set(sections)
            payload = {
                section: values
                for section, values in self.as_dict().items()
                if section in wanted
            }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
