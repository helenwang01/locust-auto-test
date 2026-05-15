from __future__ import annotations
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any


@dataclass
class PbRegistry:
    classes: Dict[str, type]

    def require(self, name: str) -> type:
        if name not in self.classes:
            raise KeyError(f"PB class not found: {name}")
        return self.classes[name]


def load_modules_from_path(path: str) -> types.ModuleType:
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"PB modules path does not exist: {path}")
    if str(path_obj) not in sys.path:
        sys.path.append(str(path_obj))
    # Import all *_pb2.py files under the path into a package-like module
    pkg_name = "pb_dynamic"
    pkg = types.ModuleType(pkg_name)
    for py in path_obj.glob("**/*_pb2.py"):
        mod_name = f"{pkg_name}." + py.with_suffix("").name
        spec = importlib.util.spec_from_file_location(mod_name, py)
        if not spec or not spec.loader:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)  # type: ignore
        setattr(pkg, py.stem, mod)
    sys.modules[pkg_name] = pkg
    return pkg


def build_registry(modules_path: str, message_map: Dict[str, str]) -> PbRegistry:
    pkg = load_modules_from_path(modules_path)
    classes: Dict[str, type] = {}
    for key, cls_name in message_map.items():
        # scan submodules to find class
        found = None
        for attr in dir(pkg):
            sub = getattr(pkg, attr)
            if isinstance(sub, types.ModuleType) and hasattr(sub, cls_name):
                found = getattr(sub, cls_name)
                break
        if not found:
            raise ImportError(f"Cannot find PB class {cls_name} in modules under {modules_path}")
        classes[key] = found  # type: ignore
    return PbRegistry(classes)


def encode(reg: PbRegistry, msg_key: str, fields: Dict[str, Any]) -> bytes:
    cls = reg.require(msg_key)
    msg = cls()
    for k, v in fields.items():
        try:
            setattr(msg, k, v)
        except Exception as e:
            raise ValueError(f"set field {k} failed: {e}")
    return msg.SerializeToString()


def decode_into(reg: PbRegistry, msg_key: str, data: bytes):
    cls = reg.require(msg_key)
    msg = cls()
    msg.ParseFromString(data)
    return msg
