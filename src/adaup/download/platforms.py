import platform as host_platform
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformInfo:
    system: str
    machine: str
    family: str
    arch: str
    executable_suffix: str
    cardano_suffix: str
    cardano_extension: str
    etcd_suffix: str
    etcd_extension: str
    hydra_suffix: str

    def hydra_artifact_name(self, version: str) -> str:
        return f"hydra-{self.hydra_suffix}-{version}"


def _normalize_system(system: str) -> str:
    normalized = (system or "").strip().lower()
    if normalized in {"windows", "cygwin", "msys"}:
        return "windows"
    if normalized == "darwin":
        return "darwin"
    if normalized == "linux":
        return "linux"
    raise ValueError(f"Unsupported platform: {system}")


def _normalize_arch(machine: str) -> str:
    normalized = (machine or "").strip().lower()
    if normalized in {"x86_64", "amd64"}:
        return "amd64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    raise ValueError(f"Unsupported architecture: {machine}")


def detect_platform(system: str | None = None, machine: str | None = None) -> PlatformInfo:
    raw_system = system or host_platform.system()
    raw_machine = machine or host_platform.machine()
    family = _normalize_system(raw_system)
    arch = _normalize_arch(raw_machine)

    if family == "linux":
        return PlatformInfo(
            system=raw_system.lower(),
            machine=raw_machine.lower(),
            family=family,
            arch=arch,
            executable_suffix="",
            cardano_suffix=f"linux-{arch}",
            cardano_extension=".tar.gz",
            etcd_suffix=f"linux-{arch}",
            etcd_extension=".tar.gz",
            hydra_suffix="x86_64-linux" if arch == "amd64" else "aarch64-linux",
        )

    if family == "darwin":
        return PlatformInfo(
            system=raw_system.lower(),
            machine=raw_machine.lower(),
            family=family,
            arch=arch,
            executable_suffix="",
            cardano_suffix=f"macos-{arch}",
            cardano_extension=".tar.gz",
            etcd_suffix=f"darwin-{arch}",
            etcd_extension=".zip",
            hydra_suffix="x86_64-darwin" if arch == "amd64" else "aarch64-darwin",
        )

    if family == "windows":
        if arch != "amd64":
            raise ValueError(f"Unsupported Windows architecture: {raw_machine}")
        return PlatformInfo(
            system=raw_system.lower(),
            machine=raw_machine.lower(),
            family=family,
            arch=arch,
            executable_suffix=".exe",
            cardano_suffix="win-amd64",
            cardano_extension=".zip",
            etcd_suffix="windows-amd64",
            etcd_extension=".zip",
            hydra_suffix="x86_64-windows",
        )

    raise ValueError(f"Unsupported platform: {raw_system}")
