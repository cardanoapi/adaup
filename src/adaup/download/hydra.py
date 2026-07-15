import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import tqdm

from .platforms import detect_platform

HYDRA_REPOSITORY = ("cardano-scaling", "hydra")
DEFAULT_HYDRA_ACTIONS_RUNS = {
    "2.2.0": "https://github.com/cardano-scaling/hydra/actions/runs/27418396480",
}
ENV_HYDRA_NODE_PATH = "ADAUP_HYDRA_NODE_PATH"
ENV_HYDRA_TUI_PATH = "ADAUP_HYDRA_TUI_PATH"
ENV_HYDRA_DOWNLOAD_URL = "ADAUP_HYDRA_DOWNLOAD_URL"
ENV_HYDRA_ACTIONS_RUN_URL = "ADAUP_HYDRA_ACTIONS_RUN_URL"


def fetch_network_json():
    """
    Download and parse the networks.json file from GitHub.

    Returns:
        dict: Parsed JSON content
    """
    url = "https://raw.githubusercontent.com/cardano-scaling/hydra/master/hydra-node/networks.json"
    print(f"Fetching network information from {url}...")

    try:
        request = Request(url, headers={"User-Agent": "adaup"})
        with urlopen(request) as response:
            content = response.read()
            return json.loads(content)
    except HTTPError as e:
        print(f"HTTP Error {e.code} for URL: {url}")
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching network information from {url}: {str(e)}")
        sys.exit(1)


def download_url(url, dest_path, headers=None):
    print(f"Downloading from {url}...")
    request_headers = {"User-Agent": "adaup"}
    if headers:
        request_headers.update(headers)
    try:
        request = Request(url, headers=request_headers)
        with urlopen(request) as response, open(dest_path, "wb") as out_file:
            total_size = int(response.headers.get("Content-Length", 0))
            chunk_size = 8192

            with tqdm.tqdm(total=total_size, unit="B", unit_scale=True, desc="Downloading") as pbar:
                while True:
                    buffer = response.read(chunk_size)
                    if not buffer:
                        break
                    out_file.write(buffer)
                    pbar.update(len(buffer))
        return dest_path
    except HTTPError as e:
        print(f"HTTP Error {e.code} for URL: {url}")
        sys.exit(1)
    except Exception as e:
        print(f"Error downloading from {url}: {str(e)}")
        print(f"Please try to download manually: {url}")
        sys.exit(1)


def installed_hydra_matches_version(hydra_node_path, hydra_version):
    try:
        result = subprocess.run(
            [hydra_node_path, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False

    version_output = (result.stdout or "") + (result.stderr or "")
    return hydra_version in version_output


def check_hydra_present(bin_dir, hydra_version=None):
    hydra_node_path = os.path.join(bin_dir, "hydra-node")
    hydra_tui_path = os.path.join(bin_dir, "hydra-tui")

    binaries_present = (
        os.path.isfile(hydra_node_path)
        and os.access(hydra_node_path, os.X_OK)
        and os.path.isfile(hydra_tui_path)
        and os.access(hydra_tui_path, os.X_OK)
    )
    if not binaries_present:
        return False

    if hydra_version is None:
        return True

    return installed_hydra_matches_version(hydra_node_path, hydra_version)


def resolve_hydra_env_paths():
    node_path = os.environ.get(ENV_HYDRA_NODE_PATH)
    tui_path = os.environ.get(ENV_HYDRA_TUI_PATH)
    if not node_path and not tui_path:
        return None
    if not node_path or not tui_path:
        raise RuntimeError(
            f"Set both {ENV_HYDRA_NODE_PATH} and {ENV_HYDRA_TUI_PATH} when overriding Hydra binaries."
        )
    return node_path, tui_path


def resolve_hydra_path_binaries():
    hydra_node_path = shutil.which("hydra-node")
    hydra_tui_path = shutil.which("hydra-tui")
    if hydra_node_path and hydra_tui_path:
        return hydra_node_path, hydra_tui_path
    return None


def validate_hydra_binary_pair(node_path, tui_path, hydra_version):
    missing = []
    for path in (node_path, tui_path):
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            missing.append(path)
    if missing:
        raise RuntimeError(
            f"Hydra binary override is missing executable files: {', '.join(missing)}"
        )
    if hydra_version and not installed_hydra_matches_version(node_path, hydra_version):
        raise RuntimeError(
            f"hydra-node at {node_path} does not match requested version {hydra_version}."
        )


def install_hydra_binary_pair(node_path, tui_path, bin_dir):
    os.makedirs(bin_dir, exist_ok=True)
    destinations = {
        "hydra-node": node_path,
        "hydra-tui": tui_path,
    }
    for name, source in destinations.items():
        destination = os.path.join(bin_dir, name)
        shutil.copy2(source, destination)
        os.chmod(destination, 0o755)
    return bin_dir


def parse_github_actions_run_url(run_url):
    parsed = urlparse(run_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 5 or parts[2] != "actions" or parts[3] != "runs":
        raise RuntimeError(
            f"Invalid Hydra Actions run URL '{run_url}'. Expected https://github.com/<owner>/<repo>/actions/runs/<id>."
        )
    return parts[0], parts[1], parts[4]


def resolve_hydra_actions_run_url(hydra_version):
    return os.environ.get(ENV_HYDRA_ACTIONS_RUN_URL) or DEFAULT_HYDRA_ACTIONS_RUNS.get(hydra_version)


def resolve_hydra_download_url(hydra_version, platform_info):
    template = os.environ.get(ENV_HYDRA_DOWNLOAD_URL)
    if not template:
        return None
    artifact = platform_info.hydra_artifact_name(hydra_version)
    return template.format(version=hydra_version, artifact=artifact)


def build_hydra_direct_archive_name(hydra_version, platform_info, url):
    path = urlparse(url).path
    basename = os.path.basename(path)
    if basename:
        return basename
    return platform_info.hydra_artifact_name(hydra_version) + ".zip"


def list_github_run_artifacts(owner, repo, run_id):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts"
    try:
        request = Request(api_url, headers={"User-Agent": "adaup"})
        with urlopen(request) as response:
            return json.load(response).get("artifacts", [])
    except HTTPError as e:
        raise RuntimeError(f"HTTP Error {e.code} while resolving Hydra artifacts from {api_url}") from e
    except Exception as e:
        raise RuntimeError(f"Error resolving Hydra artifacts from {api_url}: {str(e)}") from e


def find_hydra_artifact(artifacts, artifact_name):
    for artifact in artifacts:
        if artifact.get("name") == artifact_name and not artifact.get("expired", False):
            return artifact
    return None


def build_public_actions_artifact_url(owner, repo, artifact_id):
    return f"https://nightly.link/{owner}/{repo}/actions/artifacts/{artifact_id}.zip"


def extract_hydra_archive(archive_path, extract_to):
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            zip_ref.extractall(extract_to)
        return

    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, "r:*") as tar:
            tar.extractall(extract_to)
        return

    raise RuntimeError(f"Unsupported Hydra archive format: {archive_path}")


def find_executable(root_dir, executable_name):
    for root, _, files in os.walk(root_dir):
        if executable_name in files:
            return os.path.join(root, executable_name)
    return None


def install_hydra_from_archive(archive_path, bin_dir):
    extract_dir = tempfile.mkdtemp(prefix="hydra_extract_", dir=os.path.dirname(archive_path))
    try:
        extract_hydra_archive(archive_path, extract_dir)
        hydra_node_path = find_executable(extract_dir, "hydra-node")
        hydra_tui_path = find_executable(extract_dir, "hydra-tui")
        if hydra_node_path is None or hydra_tui_path is None:
            raise RuntimeError(
                f"Expected hydra-node and hydra-tui in extracted archive {archive_path}."
            )
        install_hydra_binary_pair(hydra_node_path, hydra_tui_path, bin_dir)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def resolve_hydra_source(hydra_version, platform_info):
    env_paths = resolve_hydra_env_paths()
    if env_paths is not None:
        return ("explicit_paths", env_paths)

    path_binaries = resolve_hydra_path_binaries()
    if path_binaries is not None:
        return ("path", path_binaries)

    direct_url = resolve_hydra_download_url(hydra_version, platform_info)
    if direct_url:
        return ("direct_url", direct_url)

    run_url = resolve_hydra_actions_run_url(hydra_version)
    if run_url:
        return ("actions_run", run_url)

    return (None, None)


def install_hydra_from_source(hydra_version, bin_dir, platform_info):
    source_kind, source_value = resolve_hydra_source(hydra_version, platform_info)
    artifact_name = platform_info.hydra_artifact_name(hydra_version)
    if source_kind is None:
        raise RuntimeError(
            "No Hydra binary source is configured for "
            f"{hydra_version} on {platform_info.family}/{platform_info.arch}. "
            f"Set {ENV_HYDRA_DOWNLOAD_URL}, {ENV_HYDRA_ACTIONS_RUN_URL}, or both "
            f"{ENV_HYDRA_NODE_PATH} and {ENV_HYDRA_TUI_PATH}."
        )

    if source_kind in {"explicit_paths", "path"}:
        node_path, tui_path = source_value
        validate_hydra_binary_pair(node_path, tui_path, hydra_version)
        install_hydra_binary_pair(node_path, tui_path, bin_dir)
        return source_kind

    tmp_download_dir = os.path.join(os.path.dirname(bin_dir), "tmp_hydra_downloads")
    os.makedirs(tmp_download_dir, exist_ok=True)
    try:
        if source_kind == "direct_url":
            archive_name = build_hydra_direct_archive_name(hydra_version, platform_info, source_value)
            archive_path = os.path.join(tmp_download_dir, archive_name)
            download_url(source_value, archive_path)
            install_hydra_from_archive(archive_path, bin_dir)
            return source_kind

        owner, repo, run_id = parse_github_actions_run_url(source_value)
        artifacts = list_github_run_artifacts(owner, repo, run_id)
        artifact = find_hydra_artifact(artifacts, artifact_name)
        if artifact is None:
            raise RuntimeError(
                f"Could not find Hydra artifact {artifact_name} in Actions run {source_value}."
            )
        artifact_id = artifact.get("id")
        if artifact_id is None:
            raise RuntimeError(f"Hydra artifact metadata is missing id for {artifact_name}.")
        archive_path = os.path.join(tmp_download_dir, artifact_name + ".zip")
        public_url = build_public_actions_artifact_url(owner, repo, artifact_id)
        download_url(public_url, archive_path)
        install_hydra_from_archive(archive_path, bin_dir)
        return source_kind
    finally:
        shutil.rmtree(tmp_download_dir, ignore_errors=True)


def hydra_install_error_message(hydra_version, platform_info):
    expected_artifact = platform_info.hydra_artifact_name(hydra_version)
    return (
        "Unable to install Hydra "
        f"{hydra_version} for {platform_info.family}/{platform_info.arch}. "
        f"Expected artifact pattern: {expected_artifact}. "
        f"Fallbacks checked in order: {ENV_HYDRA_NODE_PATH}+{ENV_HYDRA_TUI_PATH}, PATH, "
        f"{ENV_HYDRA_DOWNLOAD_URL}, {ENV_HYDRA_ACTIONS_RUN_URL}."
    )


def download_and_setup_hydra(hydra_version, bin_dir):
    print(f"Downloading and setting up Hydra {hydra_version}...")

    if check_hydra_present(bin_dir, hydra_version):
        print(
            f"Hydra executables for version {hydra_version} already exist at "
            f"{bin_dir}. Skipping download."
        )
        return os.path.join(bin_dir)
    if check_hydra_present(bin_dir):
        print(
            "Existing Hydra binaries do not match the requested version. "
            "Downloading the requested release."
        )

    os.makedirs(bin_dir, exist_ok=True)

    try:
        platform_info = detect_platform()
    except ValueError as exc:
        print(f"Error resolving Hydra platform: {exc}")
        sys.exit(1)

    try:
        source_kind = install_hydra_from_source(hydra_version, bin_dir, platform_info)
        print(f"Hydra setup complete using source: {source_kind}. Executables at: {bin_dir}")
    except Exception as exc:
        print(f"Error setting up Hydra: {exc}")
        print(hydra_install_error_message(hydra_version, platform_info))
        sys.exit(1)

    if not check_hydra_present(bin_dir, hydra_version):
        print(
            f"Error: hydra-node and hydra-tui were not installed correctly for version {hydra_version}."
        )
        sys.exit(1)

    return bin_dir
